"""
FASE 1: Create engine_registry table and populate with all engines.
FASE 2: Auto-deactivate poor engines, boost best ones, run ensemble tuning.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from sqlalchemy import text

from quant.core.db import get_db


# ── All engines/modules in the system ──────────────────────────────────────

ALL_ENGINES = [
    # Signal Engines (registered in EngineRegistry._SIGNAL_METHODS)
    {"engine_name": "technical",             "engine_type": "TECHNICAL",       "is_active": True,  "accuracy_score": 17.2,  "weight_percentage": 3.0},
    {"engine_name": "fundamental",           "engine_type": "FUNDAMENTAL",     "is_active": True,  "accuracy_score": 0.0,   "weight_percentage": 2.0},
    {"engine_name": "macro",                 "engine_type": "MACRO",           "is_active": True,  "accuracy_score": 0.0,   "weight_percentage": 2.0},
    {"engine_name": "global_market",         "engine_type": "GLOBAL_CAUSALITY","is_active": True,  "accuracy_score": 0.0,   "weight_percentage": 3.0},
    {"engine_name": "sentiment",             "engine_type": "SENTIMENT",       "is_active": True,  "accuracy_score": 0.0,   "weight_percentage": 2.0},
    {"engine_name": "relationship",          "engine_type": "RELATIONSHIP",    "is_active": True,  "accuracy_score": 0.0,   "weight_percentage": 3.0},
    {"engine_name": "alpha_mean_reversion",  "engine_type": "ALPHA",           "is_active": True,  "accuracy_score": 21.2,  "weight_percentage": 4.0},
    {"engine_name": "alpha_reversal",        "engine_type": "ALPHA",           "is_active": True,  "accuracy_score": 21.3,  "weight_percentage": 4.0},
    {"engine_name": "alpha_momentum",        "engine_type": "ALPHA",           "is_active": True,  "accuracy_score": 25.6,  "weight_percentage": 6.0},
    {"engine_name": "alpha_regime_switch",   "engine_type": "ALPHA",           "is_active": True,  "accuracy_score": 19.9,  "weight_percentage": 3.0},
    {"engine_name": "hmm_regime",            "engine_type": "REGIME",          "is_active": True,  "accuracy_score": 16.0,  "weight_percentage": 2.0},
    {"engine_name": "fama_french",           "engine_type": "FACTOR_MODEL",    "is_active": True,  "accuracy_score": 63.5,  "weight_percentage": 25.0},
    {"engine_name": "holiday_effect",        "engine_type": "TIME_CYCLE",      "is_active": True,  "accuracy_score": 0.0,   "weight_percentage": 1.0},
    {"engine_name": "volume_features",       "engine_type": "VOLUME",          "is_active": True,  "accuracy_score": 24.1,  "weight_percentage": 5.0},
    {"engine_name": "policy_events",         "engine_type": "POLICY",          "is_active": True,  "accuracy_score": 0.0,   "weight_percentage": 2.0},

    # Deep Learning / ML (unregistered modules)
    {"engine_name": "vae_feature_extractor", "engine_type": "DEEP_LEARNING",   "is_active": True,  "accuracy_score": 0.0,   "weight_percentage": 3.0},
    {"engine_name": "transformer_predictor", "engine_type": "DEEP_LEARNING",   "is_active": True,  "accuracy_score": 0.0,   "weight_percentage": 3.0},
    {"engine_name": "lstm_signal_predictor", "engine_type": "DEEP_LEARNING",   "is_active": True,  "accuracy_score": 0.0,   "weight_percentage": 3.0},
    {"engine_name": "xgb_lgbm_ensemble",     "engine_type": "ML_ENSEMBLE",     "is_active": True,  "accuracy_score": 0.0,   "weight_percentage": 4.0},
    {"engine_name": "dl_ensemble",           "engine_type": "DEEP_LEARNING",   "is_active": True,  "accuracy_score": 0.0,   "weight_percentage": 3.0},

    # Specialized Engines
    {"engine_name": "astronacci",            "engine_type": "TIME_CYCLE",      "is_active": True,  "accuracy_score": 0.0,   "weight_percentage": 5.0},
    {"engine_name": "strategy_selector",     "engine_type": "META",            "is_active": True,  "accuracy_score": 0.0,   "weight_percentage": 2.0},
    {"engine_name": "dcc_garch",             "engine_type": "VOLATILITY",      "is_active": True,  "accuracy_score": 0.0,   "weight_percentage": 3.0},
    {"engine_name": "policy_scorer",         "engine_type": "POLICY",          "is_active": True,  "accuracy_score": 0.0,   "weight_percentage": 2.0},
    {"engine_name": "causality_analyzer",    "engine_type": "CAUSALITY",       "is_active": True,  "accuracy_score": 0.0,   "weight_percentage": 4.0},

    # Agentic / AI
    {"engine_name": "screener_agent",        "engine_type": "SCREENING",       "is_active": True,  "accuracy_score": 0.0,   "weight_percentage": 2.0},
    {"engine_name": "error_pattern_learner", "engine_type": "META_LEARNING",   "is_active": True,  "accuracy_score": 0.0,   "weight_percentage": 2.0},
    {"engine_name": "self_healing_prompt",   "engine_type": "SELF_HEALING",    "is_active": True,  "accuracy_score": 0.0,   "weight_percentage": 2.0},
    {"engine_name": "agentic_orchestrator",  "engine_type": "ORCHESTRATION",   "is_active": True,  "accuracy_score": 0.0,   "weight_percentage": 2.0},
]


def create_engine_registry_table():
    """FASE 1: Create engine_registry table with feature flag columns."""
    db = get_db()
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS engine_registry (
                engine_id          SERIAL PRIMARY KEY,
                engine_name        VARCHAR(100) UNIQUE NOT NULL,
                engine_type        VARCHAR(50) NOT NULL,
                is_active          BOOLEAN NOT NULL DEFAULT TRUE,
                accuracy_score     FLOAT NOT NULL DEFAULT 0.0,
                weight_percentage  FLOAT NOT NULL DEFAULT 0.0,
                last_evaluated_at  TIMESTAMP DEFAULT NOW(),
                created_at         TIMESTAMP DEFAULT NOW(),
                updated_at         TIMESTAMP DEFAULT NOW()
            )
        """))
        db.commit()
        print("✅ Table engine_registry created")
    except Exception as e:
        print(f"⚠️ Table creation: {e}")
        db.rollback()
    finally:
        db.close()


def populate_engine_registry():
    """Populate engine_registry with all engines."""
    db = get_db()
    try:
        for eng in ALL_ENGINES:
            db.execute(text("""
                INSERT INTO engine_registry (engine_name, engine_type, is_active, accuracy_score, weight_percentage)
                VALUES (:name, :type, :active, :acc, :weight)
                ON CONFLICT (engine_name) DO UPDATE SET
                    engine_type = EXCLUDED.engine_type,
                    is_active = EXCLUDED.is_active,
                    accuracy_score = EXCLUDED.accuracy_score,
                    weight_percentage = EXCLUDED.weight_percentage,
                    updated_at = NOW()
            """), {
                "name": eng["engine_name"],
                "type": eng["engine_type"],
                "active": eng["is_active"],
                "acc": eng["accuracy_score"],
                "weight": eng["weight_percentage"],
            })
        db.commit()
        print(f"✅ Populated {len(ALL_ENGINES)} engines into engine_registry")
    except Exception as e:
        print(f"⚠️ Populate: {e}")
        db.rollback()
    finally:
        db.close()


def update_accuracy_from_sim():
    """Update accuracy scores from PREDICTION_SIM_REPORT.json."""
    report_path = Path(__file__).parent.parent / "docs" / "PREDICTION_SIM_REPORT.json"
    if not report_path.exists():
        print("⚠️ No PREDICTION_SIM_REPORT.json found")
        return

    with open(report_path) as f:
        report = json.load(f)

    db = get_db()
    try:
        for eng in report.get("engine_scores", []):
            db.execute(text("""
                UPDATE engine_registry
                SET accuracy_score = :acc, last_evaluated_at = NOW(), updated_at = NOW()
                WHERE engine_name = :name
            """), {"acc": eng["directional_accuracy"], "name": eng["engine"]})
        db.commit()
        print(f"✅ Updated accuracy scores for {len(report['engine_scores'])} engines from sim report")
    except Exception as e:
        print(f"⚠️ Update accuracy: {e}")
        db.rollback()
    finally:
        db.close()


def auto_deactivate_poor_engines(threshold: float = 20.0):
    """FASE 2: Auto-deactivate engines below accuracy threshold."""
    db = get_db()
    try:
        # Deactivate engines with accuracy below threshold (and accuracy > 0, meaning they were evaluated)
        result = db.execute(text("""
            UPDATE engine_registry
            SET is_active = FALSE, updated_at = NOW()
            WHERE accuracy_score > 0 AND accuracy_score < :threshold
            RETURNING engine_name, accuracy_score
        """), {"threshold": threshold})
        deactivated = result.fetchall()
        db.commit()

        for row in deactivated:
            print(f"  🔴 [MANAJEMEN ENGINE] Mematikan Engine: {row[0]} (Akurasi Rendah: {row[1]:.1f}%)")

        # Activate and boost engines above 50%
        result2 = db.execute(text("""
            UPDATE engine_registry
            SET is_active = TRUE, weight_percentage = LEAST(weight_percentage * 2, 50.0), updated_at = NOW()
            WHERE accuracy_score >= 50.0
            RETURNING engine_name, accuracy_score, weight_percentage
        """))
        boosted = result2.fetchall()
        db.commit()

        for row in boosted:
            print(f"  🟢 [MANAJEMEN ENGINE] Mengaktifkan Engine: {row[0]} (Bobot: {row[2]:.0f}%)")

        print(f"\n✅ Deactivated {len(deactivated)} engines (< {threshold}%)")
        print(f"✅ Boosted {len(boosted)} engines (>= 50%)")

    except Exception as e:
        print(f"⚠️ Auto-deactivate: {e}")
        db.rollback()
    finally:
        db.close()


def get_active_engines() -> list[dict]:
    """Get all active engines with their weights."""
    db = get_db()
    try:
        rows = db.execute(text("""
            SELECT engine_name, engine_type, accuracy_score, weight_percentage
            FROM engine_registry
            WHERE is_active = TRUE
            ORDER BY weight_percentage DESC
        """)).fetchall()
        return [{"engine_name": r[0], "engine_type": r[1], "accuracy_score": r[2], "weight_percentage": r[3]} for r in rows]
    finally:
        db.close()


def print_registry_status():
    """Print current registry status."""
    db = get_db()
    try:
        rows = db.execute(text("""
            SELECT engine_name, engine_type, is_active, accuracy_score, weight_percentage
            FROM engine_registry
            ORDER BY accuracy_score DESC, weight_percentage DESC
        """)).fetchall()

        print("\n" + "=" * 90)
        print("  ENGINE REGISTRY — STATUS")
        print("=" * 90)
        print(f"  {'Engine':<25} {'Type':<20} {'Active':<8} {'Accuracy':<10} {'Weight':<8}")
        print("-" * 90)
        for r in rows:
            status = "🟢" if r[2] else "🔴"
            print(f"  {r[0]:<25} {r[1]:<20} {status:<8} {r[3]:>8.1f}%  {r[4]:>6.1f}%")
        print("=" * 90)
        active_count = sum(1 for r in rows if r[2])
        print(f"  Total: {len(rows)} engines | Active: {active_count} | Inactive: {len(rows) - active_count}")
        print("=" * 90)

    finally:
        db.close()


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("  FASE 1: AUDIT INFRASTRUKTUR & ENGINE REGISTRY")
    print("=" * 70)

    # Step 1: Create table
    create_engine_registry_table()

    # Step 2: Populate with all engines
    populate_engine_registry()

    # Step 3: Update accuracy from sim report
    update_accuracy_from_sim()

    # Step 4: Print current status
    print_registry_status()

    print("\n" + "=" * 70)
    print("  FASE 2: AUTO-DEACTIVATION & WEIGHT BOOSTING")
    print("=" * 70)

    # Step 5: Auto-deactivate poor engines
    auto_deactivate_poor_engines(threshold=20.0)

    # Step 6: Print final status
    print_registry_status()
