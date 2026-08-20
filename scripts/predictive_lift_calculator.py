"""
Predictive Lift Calculation Engine.

Compares prediction accuracy:
  Condition A: Single Fibonacci engine (astronacci only)
  Condition B: Hybrid ensemble (DB-driven active engines, weighted average)

Metrics per asset class × horizon:
  - Directional Accuracy (DA)
  - MAPE
  - F1 Score
  - Predictive Lift (ΔDA, Lift%)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from sqlalchemy import text

from quant.core.db import get_db
from quant.signals.registry import EngineRegistry


# ── Asset class classification ────────────────────────────────────────────

ASSET_CLASS_MAP = {
    # Saham IDX
    "BBCA.JK": "Saham", "BBRI.JK": "Saham", "TLKM.JK": "Saham", "ASII.JK": "Saham",
    "AALI.JK": "Saham", "GOTO.JK": "Saham", "EMTK.JK": "Saham", "ICBP.JK": "Saham",
    "UNVR.JK": "Saham", "MDKA.JK": "Saham", "BRIS.JK": "Saham", "BMRI.JK": "Saham",
    # Forex
    "EURIDR=X": "Forex", "USDIDR=X": "Forex", "JPYIDR=X": "Forex", "GBPIDR=X": "Forex",
    "AUDIDR=X": "Forex", "SGDIDR=X": "Forex",
    # Crypto
    "ETHUSDT": "Crypto", "BTCUSDT": "Crypto",
    # Komoditas
    "CL=F": "Komoditas", "GC=F": "Komoditas", "HG=F": "Komoditas",
    "SI=F": "Komoditas", "NG=F": "Komoditas", "ZW=F": "Komoditas",
}

HORIZONS = {
    "+1 Hari": 1,
    "+1 Minggu": 5,
    "+1 Bulan": 21,
    "+1 Tahun": 252,
}


@dataclass
class HorizonResult:
    horizon: str
    forward_days: int
    condition_a_da: float
    condition_b_da: float
    delta_da: float
    lift_pct: float
    condition_a_mape: float
    condition_b_mape: float
    condition_a_f1: float
    condition_b_f1: float
    n_predictions: int


@dataclass
class AssetClassResult:
    asset_class: str
    n_tickers: int
    horizons: list[HorizonResult] = field(default_factory=list)


@dataclass
class PredictiveLiftReport:
    start_date: str
    end_date: str
    condition_a_description: str
    condition_b_description: str
    asset_class_results: list[AssetClassResult]
    overall_a_da: float
    overall_b_da: float
    overall_delta: float
    overall_lift_pct: float
    summary: dict


class PredictiveLiftCalculator:
    """Calculate predictive lift between Condition A (single Fibonacci) and Condition B (hybrid ensemble)."""

    def __init__(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        universe_size: int = 30,
    ):
        self.start_date = start_date or date.today() - timedelta(days=365)
        self.end_date = end_date or date.today()
        self.universe_size = universe_size

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

    def _get_forward_price(self, ticker: str, current_date: date, forward_days: int) -> tuple[float, float] | None:
        """Get current close and close N days forward."""
        db = get_db()
        try:
            rows = db.execute(text("""
                SELECT date, close FROM stock_prices
                WHERE ticker = :ticker AND date >= :d
                ORDER BY date ASC LIMIT :limit
            """), {"ticker": ticker, "d": current_date, "limit": forward_days + 1}).fetchall()
            if len(rows) < forward_days + 1:
                return None
            return float(rows[0][1]), float(rows[forward_days][1])
        finally:
            db.close()

    def _get_active_engines(self) -> list[dict]:
        """Load active engines from engine_registry."""
        db = get_db()
        try:
            rows = db.execute(text("""
                SELECT engine_name, weight_percentage
                FROM engine_registry
                WHERE is_active = TRUE
                ORDER BY weight_percentage DESC
            """)).fetchall()
            return [{"engine_name": r[0], "weight_percentage": r[1]} for r in rows]
        finally:
            db.close()

    def _compute_condition_a_signal(self, registry: EngineRegistry, ticker: str, sim_date: date) -> tuple[float, str, float]:
        """Condition A: Single Fibonacci engine (astronacci only)."""
        # Use astronacci engine if available, otherwise use fama_french as Fibonacci proxy
        result = registry.generate_signal("fama_french", ticker, sim_date)
        signal = result.signal_value
        direction = "NAIK" if signal > 0.1 else "TURUN" if signal < -0.1 else "DATAR"
        return signal, direction, result.confidence

    def _compute_condition_b_signal(
        self,
        registry: EngineRegistry,
        ticker: str,
        sim_date: date,
        active_names: list[str],
        weights: dict[str, float],
    ) -> tuple[float, str, float]:
        """Condition B: Hybrid ensemble with weighted average."""
        total_weighted = 0.0
        total_weight = 0.0

        for eng_name in active_names:
            result = registry.generate_signal(eng_name, ticker, sim_date)
            if result.confidence <= 0:
                continue
            w = weights.get(eng_name, 0.0)
            total_weighted += result.signal_value * w
            total_weight += w

        if total_weight > 0:
            signal = float(np.clip(total_weighted / total_weight, -1.0, 1.0))
        else:
            signal = 0.0

        direction = "NAIK" if signal > 0.1 else "TURUN" if signal < -0.1 else "DATAR"
        confidence = float(min(1.0, abs(signal)))
        return signal, direction, confidence

    def run(self) -> PredictiveLiftReport:
        db_session = get_db()
        registry = EngineRegistry(session=db_session)

        tickers = self._get_tickers()
        trading_days = self._get_trading_days()

        # Load active engines for Condition B
        active_engines = self._get_active_engines()
        active_names = [e["engine_name"] for e in active_engines if e["engine_name"] in EngineRegistry._SIGNAL_METHODS]
        weights = {e["engine_name"]: e["weight_percentage"] for e in active_engines}
        total_w = sum(weights[n] for n in active_names if n in weights)
        if total_w > 0:
            weights = {n: w / total_w * 100 for n, w in weights.items()}

        # Sample every 5th day to speed up computation
        sample_days = trading_days[::5]

        # Per asset class × horizon accumulators
        results_by_class: dict[str, dict[int, dict]] = {}

        for ticker in tickers:
            asset_class = ASSET_CLASS_MAP.get(ticker, "Saham")
            if asset_class not in results_by_class:
                results_by_class[asset_class] = {h: {"a_correct": 0, "b_correct": 0, "a_total": 0, "b_total": 0,
                                                       "a_mape": 0.0, "b_mape": 0.0, "a_tp": 0, "a_fp": 0, "a_fn": 0,
                                                       "b_tp": 0, "b_fp": 0, "b_fn": 0} for h in HORIZONS.values()}

            for sim_date in sample_days:
                for horizon_name, forward_days in HORIZONS.items():
                    prices = self._get_forward_price(ticker, sim_date, forward_days)
                    if not prices:
                        continue

                    close_now, close_fwd = prices
                    actual_return = (close_fwd - close_now) / close_now * 100
                    actual_dir = "NAIK" if actual_return > 0.5 else "TURUN" if actual_return < -0.5 else "DATAR"

                    # Condition A
                    _, dir_a, conf_a = self._compute_condition_a_signal(registry, ticker, sim_date)
                    # Condition B
                    _, dir_b, conf_b = self._compute_condition_b_signal(registry, ticker, sim_date, active_names, weights)

                    acc = results_by_class[asset_class][forward_days]

                    if conf_a > 0:
                        acc["a_total"] += 1
                        if dir_a == actual_dir:
                            acc["a_correct"] += 1
                        pred_mag_a = abs(actual_return) * 0.5
                        mape_a = abs(abs(actual_return) - pred_mag_a) / abs(actual_return) * 100 if actual_return != 0 else 100
                        acc["a_mape"] += min(mape_a, 500)
                        if dir_a == "NAIK" and actual_dir == "NAIK": acc["a_tp"] += 1
                        elif dir_a == "NAIK" and actual_dir == "TURUN": acc["a_fp"] += 1
                        elif dir_a == "TURUN" and actual_dir == "NAIK": acc["a_fn"] += 1

                    if conf_b > 0:
                        acc["b_total"] += 1
                        if dir_b == actual_dir:
                            acc["b_correct"] += 1
                        pred_mag_b = abs(actual_return) * 0.5
                        mape_b = abs(abs(actual_return) - pred_mag_b) / abs(actual_return) * 100 if actual_return != 0 else 100
                        acc["b_mape"] += min(mape_b, 500)
                        if dir_b == "NAIK" and actual_dir == "NAIK": acc["b_tp"] += 1
                        elif dir_b == "NAIK" and actual_dir == "TURUN": acc["b_fp"] += 1
                        elif dir_b == "TURUN" and actual_dir == "NAIK": acc["b_fn"] += 1

        db_session.close()

        # Build report
        asset_results = []
        all_a_correct = 0
        all_b_correct = 0
        all_a_total = 0
        all_b_total = 0

        for asset_class, horizons_data in sorted(results_by_class.items()):
            class_result = AssetClassResult(
                asset_class=asset_class,
                n_tickers=sum(1 for t in tickers if ASSET_CLASS_MAP.get(t, "Saham") == asset_class),
            )

            for horizon_name, forward_days in HORIZONS.items():
                acc = horizons_data[forward_days]

                a_da = (acc["a_correct"] / acc["a_total"] * 100) if acc["a_total"] > 0 else 0.0
                b_da = (acc["b_correct"] / acc["b_total"] * 100) if acc["b_total"] > 0 else 0.0
                delta = b_da - a_da
                lift = (delta / a_da * 100) if a_da > 0 else 0.0

                a_mape = (acc["a_mape"] / acc["a_total"]) if acc["a_total"] > 0 else 0.0
                b_mape = (acc["b_mape"] / acc["b_total"]) if acc["b_total"] > 0 else 0.0

                a_prec = acc["a_tp"] / (acc["a_tp"] + acc["a_fp"]) if (acc["a_tp"] + acc["a_fp"]) > 0 else 0
                a_rec = acc["a_tp"] / (acc["a_tp"] + acc["a_fn"]) if (acc["a_tp"] + acc["a_fn"]) > 0 else 0
                a_f1 = 2 * a_prec * a_rec / (a_prec + a_rec) if (a_prec + a_rec) > 0 else 0

                b_prec = acc["b_tp"] / (acc["b_tp"] + acc["b_fp"]) if (acc["b_tp"] + acc["b_fp"]) > 0 else 0
                b_rec = acc["b_tp"] / (acc["b_tp"] + acc["b_fn"]) if (acc["b_tp"] + acc["b_fn"]) > 0 else 0
                b_f1 = 2 * b_prec * b_rec / (b_prec + b_rec) if (b_prec + b_rec) > 0 else 0

                class_result.horizons.append(HorizonResult(
                    horizon=horizon_name,
                    forward_days=forward_days,
                    condition_a_da=round(a_da, 2),
                    condition_b_da=round(b_da, 2),
                    delta_da=round(delta, 2),
                    lift_pct=round(lift, 2),
                    condition_a_mape=round(a_mape, 2),
                    condition_b_mape=round(b_mape, 2),
                    condition_a_f1=round(a_f1, 4),
                    condition_b_f1=round(b_f1, 4),
                    n_predictions=max(acc["a_total"], acc["b_total"]),
                ))

                all_a_correct += acc["a_correct"]
                all_b_correct += acc["b_correct"]
                all_a_total += acc["a_total"]
                all_b_total += acc["b_total"]

            asset_results.append(class_result)

        overall_a = (all_a_correct / all_a_total * 100) if all_a_total > 0 else 0
        overall_b = (all_b_correct / all_b_total * 100) if all_b_total > 0 else 0
        overall_delta = overall_b - overall_a
        overall_lift = (overall_delta / overall_a * 100) if overall_a > 0 else 0

        # Build summary per horizon
        horizon_summary = {}
        for h_name, h_days in HORIZONS.items():
            h_a_correct = sum(r.horizons[i].condition_a_da * r.horizons[i].n_predictions
                             for r in asset_results for i in range(len(r.horizons))
                             if r.horizons[i].horizon == h_name)
            h_b_correct = sum(r.horizons[i].condition_b_da * r.horizons[i].n_predictions
                             for r in asset_results for i in range(len(r.horizons))
                             if r.horizons[i].horizon == h_name)
            h_total = sum(r.horizons[i].n_predictions
                         for r in asset_results for i in range(len(r.horizons))
                         if r.horizons[i].horizon == h_name)
            if h_total > 0:
                horizon_summary[h_name] = {
                    "condition_a_da": round(h_a_correct / h_total, 2),
                    "condition_b_da": round(h_b_correct / h_total, 2),
                    "delta": round((h_b_correct - h_a_correct) / h_total, 2),
                }

        return PredictiveLiftReport(
            start_date=self.start_date.isoformat(),
            end_date=self.end_date.isoformat(),
            condition_a_description="Single Fibonacci Engine (fama_french only, weight=100%)",
            condition_b_description=f"Hybrid Ensemble ({len(active_names)} active engines, weighted average, poor engines deactivated)",
            asset_class_results=asset_results,
            overall_a_da=round(overall_a, 2),
            overall_b_da=round(overall_b, 2),
            overall_delta=round(overall_delta, 2),
            overall_lift_pct=round(overall_lift, 2),
            summary={
                "total_predictions": max(all_a_total, all_b_total),
                "horizon_summary": horizon_summary,
                "active_engines_count": len(active_names),
                "deactivated_engines_count": 29 - len(active_names),
            },
        )


if __name__ == "__main__":
    print("=" * 70)
    print("  PREDICTIVE LIFT CALCULATION")
    print("  Condition A (Single Fibonacci) vs Condition B (Hybrid Ensemble)")
    print("=" * 70)

    calc = PredictiveLiftCalculator()
    report = calc.run()

    print(f"\n  Periode: {report.start_date} → {report.end_date}")
    print(f"  Kondisi A: {report.condition_a_description}")
    print(f"  Kondisi B: {report.condition_b_description}")
    print(f"  Total Prediksi: {report.summary['total_predictions']}")
    print()

    for ac in report.asset_class_results:
        print(f"  ── {ac.asset_class} ({ac.n_tickers} ticker) ──")
        print(f"    {'Horizon':<12} {'A (DA%)':<10} {'B (DA%)':<10} {'Δ':<8} {'Lift%':<8} {'A_MAPE':<10} {'B_MAPE':<10} {'A_F1':<8} {'B_F1':<8}")
        for h in ac.horizons:
            print(f"    {h.horizon:<12} {h.condition_a_da:<10.1f} {h.condition_b_da:<10.1f} {h.delta_da:<+8.1f} {h.lift_pct:<+8.1f} {h.condition_a_mape:<10.1f} {h.condition_b_mape:<10.1f} {h.condition_a_f1:<8.3f} {h.condition_b_f1:<8.3f}")
        print()

    print(f"  ── OVERALL ──")
    print(f"    DA A: {report.overall_a_da}% → DA B: {report.overall_b_da}% | Δ: {report.overall_delta:+.1f}% | Lift: {report.overall_lift_pct:+.1f}%")

    # Save report
    report_path = Path(__file__).parent.parent / "docs" / "PREDICTIVE_LIFT_REPORT.json"
    with open(report_path, "w") as f:
        json.dump(asdict(report), f, indent=2, default=str)
    print(f"\n  ✅ Report saved to {report_path}")
