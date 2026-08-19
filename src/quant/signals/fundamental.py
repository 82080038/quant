"""Fundamental Analysis Engine (pustaka/18 §3.2).

Scores company health and valuation based on financial ratios.

Scoring:
    PER:      min(25, max(0, 25 - PER/5))
    PBV:      min(25, max(0, 25 - PBV/0.4))
    ROE:      min(25, ROE)
    DER:      max(0, 25 - DER*25)
    Growth:   min(25, max(0, 12.5 + avg(eps_g, rev_g)))
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FundamentalScore:
    """Fundamental analysis result."""

    ticker: str
    score: float
    status: str = "ok"
    breakdown: dict[str, float] = field(default_factory=dict)
    ratios: dict[str, float | None] = field(default_factory=dict)


class FundamentalAnalysisEngine:
    """Fundamental analysis engine computing valuation and health score."""

    def analyze(
        self,
        ticker: str,
        pe: float | None = None,
        pb: float | None = None,
        roe: float | None = None,
        der: float | None = None,
        dividend_yield: float | None = None,
        eps_growth: float | None = None,
        revenue_growth: float | None = None,
    ) -> FundamentalScore:
        """Analyze fundamental ratios and return a score.

        Missing values default to neutral (12.5 per component).

        Args:
            ticker: Stock ticker.
            pe: Price-to-Earnings ratio.
            pb: Price-to-Book ratio.
            roe: Return on Equity (%).
            der: Debt-to-Equity ratio.
            dividend_yield: Dividend yield (%).
            eps_growth: EPS growth (%).
            revenue_growth: Revenue growth (%).

        Returns:
            FundamentalScore with score, breakdown, and ratios.
        """
        ratios: dict[str, float | None] = {
            "pe": pe,
            "pb": pb,
            "roe": roe,
            "der": der,
            "dividend_yield": dividend_yield,
            "eps_growth": eps_growth,
            "revenue_growth": revenue_growth,
        }

        # PER score: lower is better
        pe_score = min(25.0, max(0.0, 25.0 - pe / 5)) if pe is not None and pe > 0 else 12.5

        # PBV score: lower is better
        pb_score = min(25.0, max(0.0, 25.0 - pb / 0.4)) if pb is not None and pb > 0 else 12.5

        # ROE score: higher is better
        roe_score = min(25.0, max(0.0, roe)) if roe is not None else 12.5

        # DER score: lower is better
        der_score = max(0.0, 25.0 - der * 25) if der is not None and der >= 0 else 12.5

        # Growth score: average of EPS and revenue growth
        growth_vals: list[float] = []
        if eps_growth is not None:
            growth_vals.append(eps_growth)
        if revenue_growth is not None:
            growth_vals.append(revenue_growth)
        if growth_vals:
            avg_growth = sum(growth_vals) / len(growth_vals)
            growth_score = min(25.0, max(0.0, 12.5 + avg_growth))
        else:
            growth_score = 12.5

        total = pe_score + pb_score + roe_score + der_score + growth_score
        total = min(100.0, max(0.0, total))

        missing = sum(1 for v in [pe, pb, roe, der] if v is None)
        status = "ok" if missing == 0 else "warning" if missing < 4 else "no_data"

        return FundamentalScore(
            ticker=ticker,
            score=round(total, 2),
            status=status,
            breakdown={
                "pe": round(pe_score, 2),
                "pb": round(pb_score, 2),
                "roe": round(roe_score, 2),
                "der": round(der_score, 2),
                "growth": round(growth_score, 2),
            },
            ratios=ratios,
        )
