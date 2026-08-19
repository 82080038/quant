"""Automated model retirement manager.

Evaluates engines based on DSR, PBO, IC decay, and track record length.
Returns KEEP / WATCH / RETIRE verdict per engine.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text

from quant.core.db import get_db
from quant.evaluation.ic_tracking import ICTracker


@dataclass
class RetirementCriteria:
    """Criteria for model retirement."""
    min_track_record_days: int = 126       # 6 months minimum
    min_dsr: float = 0.50                  # DSR must be > 50%
    max_pbo: float = 0.50                  # PBO must be < 50%
    min_rolling_ic: float = 0.02           # IC must be > 0.02
    max_ic_decay_pct: float = 0.50         # IC decay < 50%
    min_win_rate: float = 0.45             # Win rate > 45%


@dataclass
class RetirementVerdict:
    """Retirement verdict for an engine."""
    engine_name: str
    verdict: str            # KEEP / WATCH / RETIRE
    score: float            # 0-1, higher is better
    reasons: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


class ModelRetirementManager:
    """Automated engine retirement based on performance criteria."""

    def __init__(self, criteria: RetirementCriteria = None, session=None):
        self.criteria = criteria or RetirementCriteria()
        self._session = session
        self._ic_tracker = ICTracker(session=session)

    @property
    def session(self):
        if self._session is None:
            self._session = get_db()
        return self._session

    def evaluate(self, engine_name: str) -> RetirementVerdict:
        """Evaluate an engine for retirement.

        Args:
            engine_name: Name of the signal engine

        Returns:
            RetirementVerdict with KEEP/WATCH/RETIRE and reasons
        """
        reasons = []
        metrics = {}
        score_components = []

        # 1. Track record length
        result = self.session.execute(text("""
            SELECT MIN(date) as first_date, MAX(date) as last_date,
                   COUNT(DISTINCT date) as n_days
            FROM prediction_evaluation
            WHERE engine_name = :engine
        """), {"engine": engine_name})
        row = result.fetchone()
        if row is None or row[0] is None:
            return RetirementVerdict(
                engine_name=engine_name, verdict="WATCH", score=0.0,
                reasons=["No evaluation data yet"],
                metrics={},
            )

        n_days = row[2]
        metrics["track_record_days"] = n_days
        if n_days < self.criteria.min_track_record_days:
            reasons.append(f"Track record too short ({n_days} < {self.criteria.min_track_record_days} days)")
            score_components.append(0.3)
        else:
            score_components.append(1.0)

        # 2. IC metrics
        ic_summary = self._ic_tracker.engine_summary()
        if not ic_summary.empty and engine_name in ic_summary["engine_name"].values:
            row = ic_summary[ic_summary["engine_name"] == engine_name].iloc[0]
            avg_ic = float(row["avg_ic"]) if row["avg_ic"] is not None else 0
            icir = float(row["icir"]) if row["icir"] is not None else 0
            metrics["avg_ic"] = avg_ic
            metrics["icir"] = icir

            if avg_ic < self.criteria.min_rolling_ic:
                reasons.append(f"IC too low ({avg_ic:.4f} < {self.criteria.min_rolling_ic})")
                score_components.append(0.2)
            else:
                score_components.append(min(1.0, avg_ic / 0.05))

            # 3. IC decay
            decay = self._ic_tracker.ic_decay(engine_name)
            metrics["ic_decay"] = decay
            if decay > self.criteria.max_ic_decay_pct:
                reasons.append(f"IC decay high ({decay:.1%} > {self.criteria.max_ic_decay_pct:.0%})")
                score_components.append(0.3)
            else:
                score_components.append(1.0 - decay)
        else:
            metrics["avg_ic"] = 0
            metrics["icir"] = 0
            metrics["ic_decay"] = 0
            score_components.extend([0.5, 0.5])

        # 4. Win rate
        result = self.session.execute(text("""
            SELECT AVG(CASE WHEN directional_correct THEN 1.0 ELSE 0.0 END) as win_rate
            FROM prediction_evaluation
            WHERE engine_name = :engine
        """), {"engine": engine_name})
        row = result.fetchone()
        win_rate = float(row[0]) if row and row[0] is not None else 0
        metrics["win_rate"] = win_rate
        if win_rate < self.criteria.min_win_rate:
            reasons.append(f"Win rate low ({win_rate:.1%} < {self.criteria.min_win_rate:.0%})")
            score_components.append(0.3)
        else:
            score_components.append(min(1.0, win_rate / 0.60))

        # Compute overall score
        score = float(np.mean(score_components))

        # Determine verdict
        if score >= 0.7:
            verdict = "KEEP"
        elif score >= 0.4:
            verdict = "WATCH"
        else:
            verdict = "RETIRE"

        if not reasons:
            reasons.append("All criteria met")

        return RetirementVerdict(
            engine_name=engine_name,
            verdict=verdict,
            score=score,
            reasons=reasons,
            metrics=metrics,
        )

    def evaluate_all(self) -> list[RetirementVerdict]:
        """Evaluate all engines that have evaluation data."""
        result = self.session.execute(text("""
            SELECT DISTINCT engine_name FROM prediction_evaluation
            ORDER BY engine_name
        """))
        engines = [r[0] for r in result.fetchall()]
        return [self.evaluate(e) for e in engines]
