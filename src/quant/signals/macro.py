"""Macro Economic Engine (pustaka/18 §3.3).

Monitors macroeconomic conditions and classifies regime.

Scoring:
    US10Y:    max(0, 25 - yield * 2.5)
    Gold:     25 if chg < 5%, 12.5 if < 10%, 0 if >= 10%
    Oil:      25 if 60-90, else 15
    USD/IDR:  25 if chg < 0, else 12.5

Regime classification:
    Tightening: US10Y rising
    Easing:     US10Y falling
    Growth:     Oil rising, USD/IDR falling
    Slowdown:   Oil falling, USD/IDR rising
    Neutral:    otherwise
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MacroScore:
    """Macro economic analysis result."""

    score: float
    regime: str
    breakdown: dict[str, float] = field(default_factory=dict)
    inputs: dict[str, float] = field(default_factory=dict)


class MacroEconomicEngine:
    """Macro economic engine computing regime and score."""

    def analyze(
        self,
        us10y_yield: float | None = None,
        us10y_prev: float | None = None,
        gold_price: float | None = None,
        gold_prev: float | None = None,
        oil_price: float | None = None,
        oil_prev: float | None = None,
        usd_idr: float | None = None,
        usd_idr_prev: float | None = None,
    ) -> MacroScore:
        """Analyze macro indicators and return regime + score.

        Args:
            us10y_yield: Current US 10Y treasury yield (%).
            us10y_prev: Previous US 10Y yield for trend.
            gold_price: Current gold price.
            gold_prev: Previous gold price for change calc.
            oil_price: Current oil price (WTI/Brent).
            oil_prev: Previous oil price for trend.
            usd_idr: Current USD/IDR rate.
            usd_idr_prev: Previous USD/IDR rate for trend.

        Returns:
            MacroScore with score, regime, breakdown, and inputs.
        """
        inputs: dict[str, float] = {}
        breakdown: dict[str, float] = {}

        # US10Y score
        if us10y_yield is not None:
            inputs["us10y"] = us10y_yield
            us10y_score = max(0.0, 25.0 - us10y_yield * 2.5)
        else:
            us10y_score = 12.5
        breakdown["us10y"] = round(us10y_score, 2)

        # Gold score
        if gold_price is not None and gold_prev is not None and gold_prev > 0:
            gold_chg = ((gold_price - gold_prev) / gold_prev) * 100
            inputs["gold_chg_pct"] = gold_chg
            if gold_chg < 5:
                gold_score = 25.0
            elif gold_chg < 10:
                gold_score = 12.5
            else:
                gold_score = 0.0
        else:
            gold_score = 12.5
        breakdown["gold"] = round(gold_score, 2)

        # Oil score
        if oil_price is not None:
            inputs["oil"] = oil_price
            oil_score = 25.0 if 60 <= oil_price <= 90 else 15.0
        else:
            oil_score = 12.5
        breakdown["oil"] = round(oil_score, 2)

        # USD/IDR score
        if usd_idr is not None and usd_idr_prev is not None and usd_idr_prev > 0:
            usd_chg = ((usd_idr - usd_idr_prev) / usd_idr_prev) * 100
            inputs["usd_idr_chg_pct"] = usd_chg
            usd_score = 25.0 if usd_chg < 0 else 12.5
        else:
            usd_score = 12.5
        breakdown["usd_idr"] = round(usd_score, 2)

        total = us10y_score + gold_score + oil_score + usd_score
        total = min(100.0, max(0.0, total))

        # Regime classification
        regime = self._classify_regime(
            us10y_yield, us10y_prev,
            oil_price, oil_prev,
            usd_idr, usd_idr_prev,
        )

        return MacroScore(
            score=round(total, 2),
            regime=regime,
            breakdown=breakdown,
            inputs=inputs,
        )

    def _classify_regime(
        self,
        us10y: float | None,
        us10y_prev: float | None,
        oil: float | None,
        oil_prev: float | None,
        usd_idr: float | None,
        usd_idr_prev: float | None,
    ) -> str:
        """Classify macro regime based on indicator trends."""
        us10y_rising = (
            us10y is not None and us10y_prev is not None and us10y > us10y_prev
        )
        us10y_falling = (
            us10y is not None and us10y_prev is not None and us10y < us10y_prev
        )
        oil_rising = (
            oil is not None and oil_prev is not None and oil > oil_prev
        )
        oil_falling = (
            oil is not None and oil_prev is not None and oil < oil_prev
        )
        usd_falling = (
            usd_idr is not None and usd_idr_prev is not None
            and usd_idr < usd_idr_prev
        )
        usd_rising = (
            usd_idr is not None and usd_idr_prev is not None
            and usd_idr > usd_idr_prev
        )

        if us10y_rising:
            return "tightening"
        if us10y_falling:
            return "easing"
        if oil_rising and usd_falling:
            return "growth"
        if oil_falling and usd_rising:
            return "slowdown"
        return "neutral"
