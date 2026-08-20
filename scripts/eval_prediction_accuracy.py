"""
Backtest Evaluation Engine — Prediksi vs Aktual Accuracy Validator.

Modul ini menguji seluruh 15+ engine prediksi terhadap data aktual di database.
Untuk setiap ticker dan tanggal T, engine menghasilkan prediksi arah (Naik/Turun)
dan estimasi perubahan. Kemudian dibandingkan dengan data aktual T+1.

Metrik:
  - Directional Accuracy (DA): persentase arah prediksi benar
  - Mean Absolute Percentage Error (MAPE): rata-rata error persentase
  - F1 Score Directional: harmonic mean precision/recall untuk arah
  - Root Cause Attribution Rate: persentase faktor pemicu terverifikasi

Decision Matrix:
  - DA >= 75%: Engine stabil, pertahankan
  - DA 50-74%: Adjust/Tune hyperparameter
  - DA < 50%: Replace dengan model time-series yang lebih tangguh
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
from sqlalchemy import text

from quant.core.db import get_db
from quant.signals.registry import EngineRegistry, ENGINE_NAMES

logger = logging.getLogger("eval_engine")


@dataclass
class PredictionRecord:
    """Satu record prediksi vs aktual."""
    engine: str
    ticker: str
    pred_date: date
    signal: float          # -1 to +1
    predicted_direction: str  # "NAIK" or "TURUN"
    predicted_magnitude: float  # estimated % change
    actual_direction: str    # "NAIK" or "TURUN"
    actual_magnitude: float  # actual % change
    direction_correct: bool
    abs_pct_error: float
    root_cause: str         # faktor pemicu utama


@dataclass
class EngineScore:
    """Skor akurasi untuk satu engine."""
    engine: str
    total_predictions: int
    directional_accuracy: float   # %
    mape: float                    # %
    f1_score: float
    precision: float
    recall: float
    root_cause_attribution: float  # %
    decision: str                  # "KEEP", "TUNE", "REPLACE"
    avg_confidence: float


@dataclass
class EvaluationReport:
    """Laporan lengkap evaluasi."""
    eval_date: str
    period_start: str
    period_end: str
    total_tickers_evaluated: int
    total_predictions: int
    engine_scores: list[EngineScore] = field(default_factory=list)
    data_gaps: list[dict[str, Any]] = field(default_factory=list)
    tuning_actions: list[dict[str, Any]] = field(default_factory=list)
    multi_horizon_projections: list[dict[str, Any]] = field(default_factory=list)


class BacktestEvaluationEngine:
    """Engine evaluasi akurasi prediksi vs aktual."""

    def __init__(self, lookback_days: int = 60, sample_tickers: int = 50):
        self.lookback_days = lookback_days
        self.sample_tickers = sample_tickers
        self.registry = EngineRegistry()
        self.predictions: list[PredictionRecord] = []

    def _get_sample_tickers(self) -> list[str]:
        """Ambil sample ticker dari stock_prices (likuid, ada data terbaru)."""
        session = get_db()
        try:
            rows = session.execute(text("""
                SELECT ticker, COUNT(*) as cnt, MAX(date) as last_date
                FROM stock_prices
                WHERE date >= CURRENT_DATE - INTERVAL '90 days'
                GROUP BY ticker
                HAVING COUNT(*) >= 30 AND MAX(date) >= CURRENT_DATE - INTERVAL '7 days'
                ORDER BY cnt DESC
                LIMIT :limit
            """), {"limit": self.sample_tickers}).fetchall()
            return [r[0] for r in rows]
        except Exception as e:
            logger.warning("Failed to get sample tickers: %s", e)
            return []
        finally:
            session.close()

    def _get_index_tickers(self) -> list[str]:
        """Ambil ticker indeks global dari market_indices + macro_data."""
        session = get_db()
        tickers = []
        try:
            rows = session.execute(text("""
                SELECT yahoo_ticker FROM market_indices
                WHERE is_active = true ORDER BY display_priority LIMIT 10
            """)).fetchall()
            tickers.extend([r[0] for r in rows if r[0]])
            # Also add macro/commodity tickers from stock_prices
            macro_tickers = session.execute(text("""
                SELECT DISTINCT ticker FROM stock_prices
                WHERE ticker IN ('ETH-USD', 'BTC-USD', 'USDIDR=X', 'CPO', 'COAL', 'COPPER')
                AND date >= CURRENT_DATE - INTERVAL '30 days'
            """)).fetchall()
            tickers.extend([r[0] for r in macro_tickers if r[0]])
        except Exception as e:
            logger.warning("Failed to get index tickers: %s", e)
        finally:
            session.close()
        return list(set(tickers))

    def _get_actual_return(self, ticker: str, pred_date: date, horizon: int = 1) -> tuple[str, float] | None:
        """Dapatkan return aktual T+horizon untuk ticker."""
        session = get_db()
        try:
            row = session.execute(text("""
                SELECT date, close FROM stock_prices
                WHERE ticker = :ticker AND date >= :pred_date
                ORDER BY date ASC LIMIT :horizon_plus_1
            """), {"ticker": ticker, "pred_date": pred_date, "horizon_plus_1": horizon + 1}).fetchall()
            if len(row) < 2:
                return None
            base_close = float(row[0][1])
            actual_close = float(row[-1][1])
            if base_close <= 0:
                return None
            pct_change = ((actual_close - base_close) / base_close) * 100.0
            direction = "NAIK" if pct_change > 0 else "TURUN"
            return (direction, pct_change)
        except Exception as e:
            logger.debug("get_actual_return failed for %s: %s", ticker, e)
            return None
        finally:
            session.close()

    def evaluate(self) -> EvaluationReport:
        """Jalankan evaluasi penuh: prediksi vs aktual untuk semua engine."""
        all_tickers = self._get_sample_tickers() + self._get_index_tickers()
        all_tickers = list(set(all_tickers))[:80]  # cap at 80

        today = date.today()
        start_date = today - timedelta(days=self.lookback_days)

        report = EvaluationReport(
            eval_date=today.isoformat(),
            period_start=start_date.isoformat(),
            period_end=today.isoformat(),
            total_tickers_evaluated=len(all_tickers),
            total_predictions=0,
        )

        # Generate predictions for each day in lookback period (sample every 5 days)
        eval_dates = []
        d = start_date
        while d <= today - timedelta(days=2):
            eval_dates.append(d)
            d += timedelta(days=5)

        logger.info("Evaluating %d tickers × %d dates × %d engines",
                     len(all_tickers), len(eval_dates), len(ENGINE_NAMES))

        for ticker in all_tickers:
            for eval_date in eval_dates:
                actual = self._get_actual_return(ticker, eval_date, horizon=1)
                if not actual:
                    continue
                actual_dir, actual_mag = actual

                try:
                    results = self.registry.generate_all(ticker, eval_date)
                except Exception:
                    continue

                for res in results:
                    if res.confidence <= 0 and "pending" in res.rationale:
                        continue
                    pred_dir = "NAIK" if res.signal_value > 0 else "TURUN" if res.signal_value < 0 else "DATAR"
                    pred_mag = abs(res.signal_value) * 5.0  # estimate: signal strength × 5% max
                    direction_correct = pred_dir == actual_dir
                    abs_pct_error = abs(abs(actual_mag) - pred_mag) if actual_mag != 0 else 100.0

                    self.predictions.append(PredictionRecord(
                        engine=res.engine_name,
                        ticker=ticker,
                        pred_date=eval_date,
                        signal=res.signal_value,
                        predicted_direction=pred_dir,
                        predicted_magnitude=pred_mag,
                        actual_direction=actual_dir,
                        actual_magnitude=actual_mag,
                        direction_correct=direction_correct,
                        abs_pct_error=min(abs_pct_error, 500.0),
                        root_cause=res.rationale[:200] if res.rationale else "Tidak teridentifikasi",
                    ))

        report.total_predictions = len(self.predictions)

        # Compute per-engine scores
        for engine_name in ENGINE_NAMES:
            engine_preds = [p for p in self.predictions if p.engine == engine_name]
            if not engine_preds:
                report.engine_scores.append(EngineScore(
                    engine=engine_name, total_predictions=0,
                    directional_accuracy=0, mape=0, f1_score=0,
                    precision=0, recall=0, root_cause_attribution=0,
                    decision="NO_DATA", avg_confidence=0,
                ))
                continue

            n = len(engine_preds)
            correct = sum(1 for p in engine_preds if p.direction_correct)
            da = (correct / n) * 100.0
            mape = sum(p.abs_pct_error for p in engine_preds) / n

            # F1 for "NAIK" class
            tp = sum(1 for p in engine_preds if p.predicted_direction == "NAIK" and p.actual_direction == "NAIK")
            fp = sum(1 for p in engine_preds if p.predicted_direction == "NAIK" and p.actual_direction == "TURUN")
            fn = sum(1 for p in engine_preds if p.predicted_direction == "TURUN" and p.actual_direction == "NAIK")
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

            # Root cause attribution: predictions with non-generic rationale
            attributed = sum(1 for p in engine_preds if p.root_cause and "pending" not in p.root_cause and "Tidak teridentifikasi" not in p.root_cause)
            rca = (attributed / n) * 100.0

            avg_conf = sum(abs(p.signal) for p in engine_preds) / n

            # Decision matrix
            if da >= 75:
                decision = "KEEP"
            elif da >= 50:
                decision = "TUNE"
            else:
                decision = "REPLACE"

            report.engine_scores.append(EngineScore(
                engine=engine_name,
                total_predictions=n,
                directional_accuracy=round(da, 2),
                mape=round(mape, 2),
                f1_score=round(f1, 4),
                precision=round(precision, 4),
                recall=round(recall, 4),
                root_cause_attribution=round(rca, 2),
                decision=decision,
                avg_confidence=round(avg_conf, 4),
            ))

        # Identify data gaps
        report.data_gaps = self._identify_data_gaps()

        # Auto-tuning actions
        report.tuning_actions = self._generate_tuning_actions(report.engine_scores)

        # Multi-horizon projections
        report.multi_horizon_projections = self._generate_multi_horizon_projections(all_tickers[:20])

        return report

    def _identify_data_gaps(self) -> list[dict[str, Any]]:
        """Identifikasi data yang kurang di database."""
        gaps = []
        session = get_db()
        try:
            # Check for missing economic calendar data
            r = session.execute(text("SELECT COUNT(*) FROM policy_events")).fetchone()
            if r[0] < 100:
                gaps.append({
                    "gap": "Kalender Ekonomi Global",
                    "description": "Data rilis berita ekonomi global (NFP, CPI, FOMC, ECB) kurang dari 100 event",
                    "current_count": r[0],
                    "needed": "500+ event ekonomi global",
                    "impact": "Prediksi volatilitas dan arah pasar meleset saat event ekonomi besar",
                })

            # Check for commodity volume data
            r = session.execute(text("SELECT COUNT(DISTINCT series_name) FROM macro_data WHERE series_name LIKE '%coal%' OR series_name LIKE '%oil%' OR series_name LIKE '%gold%' OR series_name LIKE '%copper%'")).fetchone()
            if r[0] < 5:
                gaps.append({
                    "gap": "Data Volume Komoditas",
                    "description": "Data harga komoditas (minyak, emas, tembaga, batubara) terbatas",
                    "current_count": r[0],
                    "needed": "10+ seri komoditas dengan volume perdagangan harian",
                    "impact": "Korelasi makro lintas aset tidak menangkap dampak komoditas",
                })

            # Check for foreign flow data
            r = session.execute(text("SELECT COUNT(*) FROM foreign_flow WHERE date >= CURRENT_DATE - INTERVAL '30 days'")).fetchone()
            if r[0] < 500:
                gaps.append({
                    "gap": "Data Aliran Modal Asing",
                    "description": "Data foreign flow (beli/jual asing) kurang dari 500 record 30 hari terakhir",
                    "current_count": r[0],
                    "needed": "1000+ record foreign flow harian per ticker",
                    "impact": "Sinyal tekanan jual/beli asing tidak akurat",
                })

            # Check for news sentiment coverage
            r = session.execute(text("SELECT COUNT(DISTINCT ticker) FROM news_sentiment WHERE date >= CURRENT_DATE - INTERVAL '30 days'")).fetchone()
            if r[0] < 50:
                gaps.append({
                    "gap": "Coverage Sentimen Berita",
                    "description": "Hanya sedikit ticker yang memiliki data sentimen berita 30 hari terakhir",
                    "current_count": r[0],
                    "needed": "200+ ticker dengan sentimen berita harian",
                    "impact": "Engine sentimen tidak dapat menghasilkan sinyal untuk mayoritas ticker",
                })

            # Check for crypto/forex data
            r = session.execute(text("SELECT COUNT(*) FROM stock_prices WHERE ticker IN ('ETH-USD', 'BTC-USD', 'USDIDR=X') AND date >= CURRENT_DATE - INTERVAL '30 days'")).fetchone()
            if r[0] < 60:
                gaps.append({
                    "gap": "Data Crypto & Forex",
                    "description": "Data harga ETH, BTC, dan USD/IDR kurang lengkap",
                    "current_count": r[0],
                    "needed": "90+ hari data harian untuk ETH, BTC, USD/IDR",
                    "impact": "Prediksi korelasi crypto-forex-equity tidak akurat",
                })

        except Exception as e:
            logger.warning("Data gap identification failed: %s", e)
        finally:
            session.close()
        return gaps

    def _generate_tuning_actions(self, scores: list[EngineScore]) -> list[dict[str, Any]]:
        """Generate auto-tuning actions untuk engine di bawah 75% accuracy."""
        actions = []
        for score in scores:
            if score.decision == "TUNE":
                actions.append({
                    "engine": score.engine,
                    "action": "ADJUST",
                    "current_da": score.directional_accuracy,
                    "target_da": 75.0,
                    "tuning_params": {
                        "weight_adjustment": "Tingkatkan bobot korelasi makro sebesar 15%",
                        "time_lag_shift": "Geser jeda waktu dari T+1 ke T+2 untuk korelasi makro",
                        "fibonacci_pivot_refinement": "Perbaiki titik koordinat Fibonacci dengan pivot point harian",
                    },
                })
            elif score.decision == "REPLACE":
                actions.append({
                    "engine": score.engine,
                    "action": "REPLACE",
                    "current_da": score.directional_accuracy,
                    "replacement_model": "ARIMA/GARCH time-series model dengan volatilitas kondisional",
                    "rationale": "Engine gagal menghasilkan arah yang benar (<50% DA), perlu model runtun waktu yang lebih tangguh",
                })
        return actions

    def _generate_multi_horizon_projections(self, tickers: list[str]) -> list[dict[str, Any]]:
        """Generate proyeksi multi-horizon: +1 Hari, +1 Minggu, +1 Bulan, +1 Tahun."""
        projections = []
        today = date.today()
        horizons = [
            ("+1Hari", 1),
            ("+1Minggu", 5),
            ("+1Bulan", 22),
            ("+1Tahun", 252),
        ]

        for ticker in tickers[:15]:
            try:
                results = self.registry.generate_all(ticker, today)
                composite_signal = np.mean([r.signal_value for r in results if r.confidence > 0]) if any(r.confidence > 0 for r in results) else 0
                confidence = np.mean([r.confidence for r in results if r.confidence > 0]) if any(r.confidence > 0 for r in results) else 0

                # Find top contributing engine
                top_engine = max(results, key=lambda r: abs(r.signal_value)) if results else None

                for horizon_name, horizon_days in horizons:
                    # Scale magnitude by sqrt(time) for longer horizons
                    magnitude = abs(composite_signal) * 5.0 * np.sqrt(horizon_days / 5.0)
                    direction = "NAIK" if composite_signal > 0 else "TURUN" if composite_signal < 0 else "DATAR"

                    projections.append({
                        "ticker": ticker,
                        "horizon": horizon_name,
                        "horizon_days": horizon_days,
                        "direction": direction,
                        "estimated_magnitude_pct": round(magnitude, 2),
                        "confidence": round(confidence, 4),
                        "root_cause": top_engine.rationale[:200] if top_engine and top_engine.rationale else "Kombinasi sinyal multi-engine",
                        "top_engine": top_engine.engine_name if top_engine else "composite",
                    })
            except Exception as e:
                logger.debug("Projection failed for %s: %s", ticker, e)

        return projections

    def save_report(self, report: EvaluationReport, path: str | Path) -> None:
        """Simpan laporan evaluasi ke JSON."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        report_dict = {
            "eval_date": report.eval_date,
            "period_start": report.period_start,
            "period_end": report.period_end,
            "total_tickers_evaluated": report.total_tickers_evaluated,
            "total_predictions": report.total_predictions,
            "engine_scores": [asdict(s) for s in report.engine_scores],
            "data_gaps": report.data_gaps,
            "tuning_actions": report.tuning_actions,
            "multi_horizon_projections": report.multi_horizon_projections,
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(report_dict, f, indent=2, default=str, ensure_ascii=False)

        logger.info("Evaluation report saved to %s", path)


def main():
    """Run evaluation and print summary."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")

    engine = BacktestEvaluationEngine(lookback_days=60, sample_tickers=50)
    report = engine.evaluate()

    # Save report
    report_path = Path(__file__).parent.parent / "docs" / "PREDICTION_EVALUATION_REPORT.json"
    engine.save_report(report, report_path)

    # Print summary
    print("\n" + "=" * 70)
    print("  LAPORAN EVALUASI PREDIKSI ENGINE")
    print("=" * 70)
    print(f"  Tanggal Evaluasi: {report.eval_date}")
    print(f"  Periode: {report.period_start} → {report.period_end}")
    print(f"  Ticker Dievaluasi: {report.total_tickers_evaluated}")
    print(f"  Total Prediksi: {report.total_predictions}")
    print()

    print(f"  {'Engine':<25} {'DA%':>6} {'MAPE%':>7} {'F1':>6} {'Decision':<10} {'N':>5}")
    print("  " + "-" * 65)
    for score in sorted(report.engine_scores, key=lambda s: s.directional_accuracy, reverse=True):
        print(f"  {score.engine:<25} {score.directional_accuracy:>6.1f} {score.mape:>7.1f} {score.f1_score:>6.3f} {score.decision:<10} {score.total_predictions:>5}")

    print()
    print(f"  Data Gaps Ditemukan: {len(report.data_gaps)}")
    for gap in report.data_gaps:
        print(f"    - {gap['gap']}: {gap['description']}")

    print()
    print(f"  Tuning Actions: {len(report.tuning_actions)}")
    for action in report.tuning_actions:
        print(f"    - {action['engine']}: {action['action']} (DA: {action['current_da']:.1f}%)")

    print()
    print(f"  Proyeksi Multi-Horizon: {len(report.multi_horizon_projections)}")
    for proj in report.multi_horizon_projections[:5]:
        print(f"    - {proj['ticker']} {proj['horizon']}: {proj['direction']} {proj['estimated_magnitude_pct']:.2f}% (conf: {proj['confidence']:.2f})")

    print("\n" + "=" * 70)
    print(f"  Laporan JSON: {report_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
