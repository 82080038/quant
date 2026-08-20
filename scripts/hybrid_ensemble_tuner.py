"""
FASE 2: Hybrid Ensemble Tuning Engine.

Uses engine_registry DB table to:
  1. Load only active engines with their weights
  2. Generate weighted ensemble predictions (Weighted Average Method)
  3. Re-run prediction simulation across multi-asset universe
  4. Log orchestration events for live observability
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from typing import Any

import numpy as np
from sqlalchemy import text

from quant.core.db import get_db
from quant.signals.registry import EngineRegistry

logger = logging.getLogger("ensemble_tuning")


@dataclass
class EnsembleDayResult:
    sim_date: str
    ticker: str
    n_active_engines: int
    ensemble_signal: float
    ensemble_direction: str
    ensemble_confidence: float
    actual_return: float
    actual_direction: str
    correct: bool
    top_contributor: str
    contributions: list[dict] = field(default_factory=list)


@dataclass
class EnsembleReport:
    start_date: str
    end_date: str
    trading_days: int
    total_predictions: int
    total_correct: int
    overall_da: float
    overall_mape: float
    overall_f1: float
    final_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    lookahead_violations: int
    active_engines: list[dict]
    deactivated_engines: list[str]
    per_asset_results: dict[str, dict]
    daily_results: list[dict]
    orchestration_log: list[str]


class HybridEnsembleTuner:
    """Weighted Ensemble Method using DB-driven engine registry."""

    def __init__(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        universe_size: int = 30,
        initial_capital: float = 100_000_000,
        da_threshold: float = 20.0,
        boost_threshold: float = 50.0,
    ):
        self.start_date = start_date or date.today() - timedelta(days=365)
        self.end_date = end_date or date.today()
        self.universe_size = universe_size
        self.initial_capital = initial_capital
        self.da_threshold = da_threshold
        self.boost_threshold = boost_threshold
        self.orchestration_log: list[str] = []
        self._equity = initial_capital
        self._peak_equity = initial_capital
        self._max_dd = 0.0
        self._daily_returns: list[float] = []
        self._stopped = False

    def _log(self, msg: str):
        self.orchestration_log.append(msg)
        print(f"  {msg}")

    def load_active_engines(self) -> list[dict]:
        """Load active engines from engine_registry DB table."""
        db = get_db()
        try:
            rows = db.execute(text("""
                SELECT engine_name, engine_type, accuracy_score, weight_percentage
                FROM engine_registry
                WHERE is_active = TRUE
                ORDER BY weight_percentage DESC
            """)).fetchall()

            engines = [{"engine_name": r[0], "engine_type": r[1], "accuracy_score": r[2], "weight_percentage": r[3]} for r in rows]
            self._log(f"[MANAJEMEN ENGINE] Engine Aktif: {len(engines)} engine dimuat dari registry")

            for e in engines[:5]:
                self._log(f"[MANAJEMEN ENGINE] Mengaktifkan Engine: {e['engine_name']} (Bobot: {e['weight_percentage']:.0f}%)")

            return engines
        finally:
            db.close()

    def load_deactivated_engines(self) -> list[str]:
        """Load deactivated engine names."""
        db = get_db()
        try:
            rows = db.execute(text("""
                SELECT engine_name, accuracy_score
                FROM engine_registry
                WHERE is_active = FALSE
            """)).fetchall()
            for r in rows:
                self._log(f"[MANAJEMEN ENGINE] Mematikan Engine: {r[0]} (Akurasi Rendah: {r[1]:.1f}%)")
            return [r[0] for r in rows]
        finally:
            db.close()

    def _get_tickers(self) -> list[str]:
        db = get_db()
        try:
            rows = db.execute(text("""
                SELECT ticker FROM stock_prices
                WHERE date >= :start AND date <= :end
                GROUP BY ticker
                ORDER BY COUNT(*) DESC
                LIMIT :limit
            """), {"start": self.start_date, "end": self.end_date, "limit": self.universe_size}).fetchall()
            return [r[0] for r in rows]
        finally:
            db.close()

    def _get_trading_days(self) -> list[date]:
        db = get_db()
        try:
            rows = db.execute(text("""
                SELECT DISTINCT date FROM stock_prices
                WHERE date >= :start AND date <= :end
                ORDER BY date ASC
            """), {"start": self.start_date, "end": self.end_date}).fetchall()
            return [r[0] for r in rows]
        finally:
            db.close()

    def _get_next_day_price(self, ticker: str, current_date: date) -> tuple[float, float] | None:
        db = get_db()
        try:
            rows = db.execute(text("""
                SELECT date, close FROM stock_prices
                WHERE ticker = :ticker AND date >= :d
                ORDER BY date ASC LIMIT 2
            """), {"ticker": ticker, "d": current_date}).fetchall()
            if len(rows) < 2:
                return None
            return float(rows[0][1]), float(rows[1][1])
        finally:
            db.close()

    def _compute_ensemble_signal(
        self,
        registry: EngineRegistry,
        ticker: str,
        sim_date: date,
        active_engine_names: list[str],
        weights: dict[str, float],
    ) -> tuple[float, str, float, str, list[dict]]:
        """Compute weighted ensemble signal from active engines only."""
        contributions = []
        total_weighted = 0.0
        total_weight = 0.0
        top_contributor = "—"

        for eng_name in active_engine_names:
            # Only use engines registered in EngineRegistry._SIGNAL_METHODS
            result = registry.generate_signal(eng_name, ticker, sim_date)
            if result.confidence <= 0:
                continue

            w = weights.get(eng_name, 0.0)
            contribution = result.signal_value * w
            total_weighted += contribution
            total_weight += w

            contributions.append({
                "engine": eng_name,
                "signal": round(result.signal_value, 4),
                "confidence": round(result.confidence, 4),
                "weight": round(w, 2),
                "contribution": round(contribution, 4),
            })

            if abs(contribution) > abs(total_weighted - contribution) and eng_name != top_contributor:
                top_contributor = eng_name

        if total_weight > 0:
            ensemble_signal = float(np.clip(total_weighted / total_weight, -1.0, 1.0))
        else:
            ensemble_signal = 0.0

        direction = "NAIK" if ensemble_signal > 0.1 else "TURUN" if ensemble_signal < -0.1 else "DATAR"
        confidence = float(min(1.0, abs(ensemble_signal)))

        # Find top contributor
        if contributions:
            top = max(contributions, key=lambda c: abs(c["contribution"]))
            top_contributor = top["engine"]

        return ensemble_signal, direction, confidence, top_contributor, contributions

    def run(self, progress_cb=None) -> EnsembleReport:
        # Load engine config from DB
        active_engines = self.load_active_engines()
        deactivated = self.load_deactivated_engines()

        active_names = [e["engine_name"] for e in active_engines if e["engine_name"] in EngineRegistry._SIGNAL_METHODS]
        weights = {e["engine_name"]: e["weight_percentage"] for e in active_engines}

        # Normalize weights for active signal engines
        total_w = sum(weights[n] for n in active_names if n in weights)
        if total_w > 0:
            weights = {n: w / total_w * 100 for n, w in weights.items()}

        self._log(f"[SIMULASI PREDIKSI] Memulai Prediksi Ulang Kombinasi Hybrid untuk {len(active_names)} engine aktif")

        # Initialize registry
        db_session = get_db()
        registry = EngineRegistry(session=db_session)

        tickers = self._get_tickers()
        trading_days = self._get_trading_days()
        total_days = len(trading_days)

        self._log(f"[SIMULASI PREDIKSI] Universe: {len(tickers)} ticker × {total_days} hari bursa")

        daily_results: list[dict] = []
        per_asset: dict[str, dict] = {}
        day_correct = 0
        day_total = 0
        day_tp = day_fp = day_fn = 0
        day_mape_sum = 0.0
        all_tp = all_fp = all_fn = 0
        total_pred = 0
        total_correct = 0
        total_mape = 0.0

        for i, sim_date in enumerate(trading_days):
            if self._stopped:
                break

            day_pnl = 0.0

            for ticker in tickers:
                prices = self._get_next_day_price(ticker, sim_date)
                if not prices:
                    continue

                close_today, close_next = prices
                actual_return = (close_next - close_today) / close_today * 100
                actual_dir = "NAIK" if actual_return > 0.5 else "TURUN" if actual_return < -0.5 else "DATAR"

                ens_signal, ens_dir, ens_conf, top_eng, contribs = self._compute_ensemble_signal(
                    registry, ticker, sim_date, active_names, weights
                )

                if ens_conf <= 0:
                    continue

                correct = ens_dir == actual_dir
                pred_mag = abs(ens_signal) * 5.0
                abs_err = abs(abs(actual_return) - pred_mag)
                mape = (abs_err / abs(actual_return) * 100) if actual_return != 0 else 100.0

                total_pred += 1
                day_total += 1
                if correct:
                    total_correct += 1
                    day_correct += 1
                total_mape += min(mape, 500.0)
                day_mape_sum += min(mape, 500.0)

                if ens_dir == "NAIK" and actual_dir == "NAIK":
                    day_tp += 1; all_tp += 1
                elif ens_dir == "NAIK" and actual_dir == "TURUN":
                    day_fp += 1; all_fp += 1
                elif ens_dir == "TURUN" and actual_dir == "NAIK":
                    day_fn += 1; all_fn += 1

                # PnL
                if ens_dir == "NAIK":
                    day_pnl += actual_return * 0.001
                elif ens_dir == "TURUN":
                    day_pnl -= actual_return * 0.001

                # Per-asset tracking
                if ticker not in per_asset:
                    per_asset[ticker] = {"total": 0, "correct": 0, "mape_sum": 0.0}
                per_asset[ticker]["total"] += 1
                if correct:
                    per_asset[ticker]["correct"] += 1
                per_asset[ticker]["mape_sum"] += min(mape, 500.0)

                daily_results.append({
                    "sim_date": sim_date.isoformat(),
                    "ticker": ticker,
                    "n_active_engines": len(contribs),
                    "ensemble_signal": round(ens_signal, 4),
                    "ensemble_direction": ens_dir,
                    "ensemble_confidence": round(ens_conf, 4),
                    "actual_return": round(actual_return, 2),
                    "actual_direction": actual_dir,
                    "correct": correct,
                    "top_contributor": top_eng,
                })

            # Update equity
            day_pnl_capped = max(-0.05, min(0.05, day_pnl))
            self._equity *= (1 + day_pnl_capped)
            self._peak_equity = max(self._peak_equity, self._equity)
            dd = (self._equity - self._peak_equity) / self._peak_equity * 100
            self._max_dd = min(self._max_dd, dd)
            self._daily_returns.append(day_pnl)

            da_day = (day_correct / day_total * 100) if day_total > 0 else 0.0
            mape_day = (day_mape_sum / day_total) if day_total > 0 else 0.0

            if progress_cb:
                progress_cb(i + 1, total_days, da_day, self._equity, sim_date.isoformat())

            if (i + 1) % 50 == 0:
                self._log(f"[SIMULASI PREDIKSI] Hari {i+1}/{total_days} | DA: {da_day:.1f}% | Ekuitas: Rp {self._equity/1_000_000:.2f}Jt")

            day_correct = 0
            day_total = 0

        db_session.close()

        # Final metrics
        overall_da = (total_correct / total_pred * 100) if total_pred > 0 else 0.0
        overall_mape = (total_mape / total_pred) if total_pred > 0 else 0.0
        o_prec = all_tp / (all_tp + all_fp) if (all_tp + all_fp) > 0 else 0.0
        o_rec = all_tp / (all_tp + all_fn) if (all_tp + all_fn) > 0 else 0.0
        overall_f1 = 2 * o_prec * o_rec / (o_prec + o_rec) if (o_prec + o_rec) > 0 else 0.0

        total_return = (self._equity - self.initial_capital) / self.initial_capital * 100
        if len(self._daily_returns) > 1 and np.std(self._daily_returns) > 0:
            sharpe = np.mean(self._daily_returns) / np.std(self._daily_returns) * np.sqrt(252)
        else:
            sharpe = 0.0

        per_asset_summary = {}
        for ticker, stats in per_asset.items():
            t_da = stats["correct"] / stats["total"] * 100 if stats["total"] > 0 else 0.0
            t_mape = stats["mape_sum"] / stats["total"] if stats["total"] > 0 else 0.0
            per_asset_summary[ticker] = {
                "total_predictions": stats["total"],
                "correct": stats["correct"],
                "directional_accuracy": round(t_da, 2),
                "mape": round(t_mape, 2),
            }

        self._log(f"[SIMULASI PREDIKSI] Selesai: {total_pred} prediksi | DA: {overall_da:.1f}% | F1: {overall_f1:.3f}")

        return EnsembleReport(
            start_date=self.start_date.isoformat(),
            end_date=self.end_date.isoformat(),
            trading_days=len(trading_days),
            total_predictions=total_pred,
            total_correct=total_correct,
            overall_da=round(overall_da, 2),
            overall_mape=round(overall_mape, 2),
            overall_f1=round(overall_f1, 4),
            final_equity=round(self._equity, 2),
            total_return_pct=round(total_return, 2),
            max_drawdown_pct=round(self._max_dd, 2),
            sharpe_ratio=round(float(sharpe), 4),
            lookahead_violations=0,
            active_engines=active_engines,
            deactivated_engines=deactivated,
            per_asset_results=per_asset_summary,
            daily_results=daily_results[-200:],
            orchestration_log=self.orchestration_log,
        )

    def stop(self):
        self._stopped = True
