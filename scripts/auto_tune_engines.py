"""
Auto-Tuning Engine — Penalaan parameter otomotis berdasarkan skor akurasi.

Modul ini menala engine yang berkinerja di bawah 75% Directional Accuracy:
  - Adjust: tingkatkan bobot korelasi makro, geser time-lag, perbaiki Fibonacci pivots
  - Replace: ganti dengan model ARIMA/GARCH untuk engine yang gagal total (<50% DA)

Hasil penalaan disimpan ke tabel `engine_tuning_params` untuk digunakan oleh registry.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import text

from quant.core.db import get_db

logger = logging.getLogger("auto_tuner")


def apply_tuning(tuning_actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply tuning actions to engine parameters stored in DB."""
    results = []
    session = get_db()
    try:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS engine_tuning_params (
                id SERIAL PRIMARY KEY,
                engine_name TEXT NOT NULL,
                param_key TEXT NOT NULL,
                param_value JSONB NOT NULL,
                tuned_at TIMESTAMPTZ DEFAULT NOW(),
                previous_value JSONB,
                tuning_reason TEXT,
                UNIQUE(engine_name, param_key)
            )
        """))
        session.commit()

        for action in tuning_actions:
            engine_name = action["engine"]
            action_type = action["action"]

            if action_type == "ADJUST":
                params = action.get("tuning_params", {})
                for param_key, param_value in params.items():
                    session.execute(text("""
                        INSERT INTO engine_tuning_params (engine_name, param_key, param_value, tuning_reason)
                        VALUES (:engine, :key, CAST(:value AS JSONB), :reason)
                        ON CONFLICT (engine_name, param_key)
                        DO UPDATE SET param_value = CAST(:value AS JSONB), tuned_at = NOW(), tuning_reason = :reason
                    """), {
                        "engine": engine_name,
                        "key": param_key,
                        "value": json.dumps({"value": param_value}),
                        "reason": f"Auto-tune: DA={action['current_da']:.1f}%, target=75%",
                    })
                    results.append({
                        "engine": engine_name,
                        "param": param_key,
                        "action": "ADJUSTED",
                        "value": param_value,
                    })

            elif action_type == "REPLACE":
                replacement = action.get("replacement_model", "ARIMA/GARCH")
                session.execute(text("""
                    INSERT INTO engine_tuning_params (engine_name, param_key, param_value, tuning_reason)
                    VALUES (:engine, :key, CAST(:value AS JSONB), :reason)
                    ON CONFLICT (engine_name, param_key)
                    DO UPDATE SET param_value = CAST(:value AS JSONB), tuned_at = NOW(), tuning_reason = :reason
                """), {
                    "engine": engine_name,
                    "key": "replacement_model",
                    "value": json.dumps({"model": replacement, "active": True}),
                    "reason": f"Replace: DA={action['current_da']:.1f}% < 50%, switch to {replacement}",
                })
                results.append({
                    "engine": engine_name,
                    "param": "replacement_model",
                    "action": "REPLACED",
                    "value": replacement,
                })

        session.commit()
        logger.info("Applied %d tuning actions", len(results))

    except Exception as e:
        session.rollback()
        logger.error("Tuning failed: %s", e)
    finally:
        session.close()

    return results


def get_tuned_params(engine_name: str) -> dict[str, Any]:
    """Retrieve tuned parameters for an engine."""
    session = get_db()
    try:
        rows = session.execute(text("""
            SELECT param_key, param_value FROM engine_tuning_params
            WHERE engine_name = :engine ORDER BY tuned_at DESC
        """), {"engine": engine_name}).fetchall()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}
    finally:
        session.close()


def main():
    """Run auto-tuning from evaluation report."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")

    report_path = Path(__file__).parent.parent / "docs" / "PREDICTION_EVALUATION_REPORT.json"
    if not report_path.exists():
        logger.error("Evaluation report not found at %s. Run eval_prediction_accuracy.py first.", report_path)
        return

    with open(report_path, "r") as f:
        report = json.load(f)

    tuning_actions = report.get("tuning_actions", [])
    if not tuning_actions:
        print("No tuning actions needed — all engines above threshold.")
        return

    print(f"\nApplying {len(tuning_actions)} tuning actions...")
    results = apply_tuning(tuning_actions)

    print(f"\nTuning Results ({len(results)} params adjusted):")
    for r in results:
        print(f"  {r['engine']:25s} {r['param']:30s} {r['action']:10s} → {r['value']}")

    print(f"\n✅ Tuning complete. Parameters stored in engine_tuning_params table.")


if __name__ == "__main__":
    main()
