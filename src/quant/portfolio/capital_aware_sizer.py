"""Capital-Aware Position Sizer (catatan.md TAHAP 6 -- Prompt 6.1).

Position sizing yang:
1. Query ``user_trading_profiles`` untuk available capital.
2. Query ``instrument_behavior_profiles`` untuk liquidity constraints.
3. Apply Kelly criterion dengan max 25% of optimal (quarter-Kelly prudence).
4. Generate human-readable reasoning untuk setiap sizing decision.

Output: ``PositionSizingResult`` dengan:
- shares (lot 100 untuk IDX)
- value_idr (rupiah)
- kelly_fraction, kelly_capped
- risk_per_trade_idr
- reasoning (Bahasa Indonesia)

Integrasi:
- Dipakai oleh ``EnhancedSignalGenerator`` dan ``RecommendationEngine``.
- Respect ``optimal_position_size_pct`` dari instrument profile (liquidity cap).
- Respect ``max_loss_per_trade_pct`` dari user profile (risk cap).

Referensi:
- catatan.md L659-L668 (Prompt 6.1)
- pustaka/92-multi-market-multi-asset-trading-system.md §7 (Risk Management)
- Kelly, J.L. (1956). "A New Interpretation of Information Rate"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from quant.advisory.trading_style_advisor import TradingStyleAdvisor
from quant.analysis.instrument_profiler import (
    InstrumentBehaviorProfiler,
    InstrumentProfile,
)
from quant.risk.cost_model import TradingCostModel

logger = logging.getLogger(__name__)

# IDX lot size
_IDX_LOT_SIZE = 100
# Quarter-Kelly: max 25% of full Kelly (prudence per catatan.md L666)
_KELLY_CAP_FRACTION = 0.25
# Absolute max position size as % of portfolio (regulatory prudence)
_MAX_POSITION_PCT_OF_PORTFOLIO = 0.20
# Default max loss per trade if user profile doesn't specify
_DEFAULT_MAX_LOSS_PCT = 2.0


@dataclass
class PositionSizingResult:
    """Result of capital-aware position sizing for one instrument."""

    ticker: str
    direction: int  # +1 BUY, -1 SELL, 0 HOLD
    # Sizing
    shares: int = 0
    lots: int = 0
    value_idr: float = 0.0
    position_pct_of_portfolio: float = 0.0
    # Kelly
    kelly_fraction_raw: float = 0.0
    kelly_fraction_capped: float = 0.0
    # Risk
    risk_per_trade_idr: float = 0.0
    stop_loss_price: float | None = None
    # Constraints applied
    liquidity_cap_pct: float | None = None
    risk_cap_pct: float | None = None
    portfolio_cap_pct: float | None = None
    # Reasoning
    reasoning: str = ""
    reasoning_steps: list[str] = field(default_factory=list)
    # Context
    entry_price: float | None = None
    available_capital: float = 0.0
    style_allocation_pct: float = 0.0  # allocation for this signal's style
    # Trading costs
    estimated_entry_cost_idr: float = 0.0
    estimated_round_trip_cost_idr: float = 0.0
    round_trip_cost_rate: float = 0.0
    # Decision
    approved: bool = True
    rejection_reason: str = ""


class CapitalAwarePositionSizer:
    """Position sizer yang menggabungkan Kelly + liquidity + risk constraints.

    Usage:
        sizer = CapitalAwarePositionSizer()
        result = sizer.size_position(
            ticker="BBCA.JK",
            direction=1,
            entry_price=8500,
            win_rate=0.55,
            win_loss_ratio=1.5,
            target_style="swing",
            user_id="default",
        )
    """

    def __init__(
        self,
        profiler: InstrumentBehaviorProfiler | None = None,
        advisor: TradingStyleAdvisor | None = None,
        cost_model: TradingCostModel | None = None,
        kelly_cap_fraction: float = _KELLY_CAP_FRACTION,
        max_position_pct: float = _MAX_POSITION_PCT_OF_PORTFOLIO,
        lot_size: int = _IDX_LOT_SIZE,
    ) -> None:
        self.profiler = profiler or InstrumentBehaviorProfiler()
        self.advisor = advisor or TradingStyleAdvisor()
        self.cost_model = cost_model or TradingCostModel()
        self.kelly_cap_fraction = kelly_cap_fraction
        self.max_position_pct = max_position_pct
        self.lot_size = lot_size

    def size_position(
        self,
        ticker: str,
        direction: int,
        entry_price: float,
        win_rate: float = 0.55,
        win_loss_ratio: float = 1.5,
        target_style: str = "swing",
        user_id: str = "default",
        portfolio_override: float | None = None,
    ) -> PositionSizingResult:
        """Size a position combining Kelly + liquidity + risk + portfolio caps.

        Args:
            ticker: Instrument ticker.
            direction: +1 BUY, -1 SELL, 0 HOLD.
            entry_price: Entry price per share (IDR).
            win_rate: Historical win rate of the signal generator (0-1).
            win_loss_ratio: Avg win / avg loss.
            target_style: intraday/swing/investing -- determines allocation slice.
            user_id: User profile ID for capital + risk tolerance.
            portfolio_override: Override total portfolio (skip user profile lookup).
        """
        result = PositionSizingResult(
            ticker=ticker, direction=direction, entry_price=entry_price,
        )
        if direction == 0:
            result.approved = False
            result.rejection_reason = "HOLD signal -- no position"
            result.reasoning = "Sinyal HOLD -- tidak ada posisi yang diambil."
            return result

        # 1. Load user profile for capital + risk tolerance
        user_profile = self.advisor.get_profile(user_id)
        if portfolio_override is not None:
            total_capital = portfolio_override
            max_loss_pct = _DEFAULT_MAX_LOSS_PCT
        elif user_profile is not None:
            total_capital = user_profile.capital
            max_loss_pct = (
                float(user_profile.max_loss_per_trade_pct)
                if user_profile.max_loss_per_trade_pct
                else _DEFAULT_MAX_LOSS_PCT
            )
        else:
            result.approved = False
            result.rejection_reason = f"No user profile for {user_id}"
            result.reasoning = f"Profil user {user_id} tidak ditemukan -- tidak bisa sizing."
            return result

        # 2. Get style allocation % from TradingStyleAdvisor
        #    When portfolio_override is set, treat it as the full available
        #    capital for this single position (skip style slicing).
        if portfolio_override is not None:
            style_allocation_pct = 100.0
            style_capital = total_capital
        elif user_profile is not None:
            try:
                rec = self.advisor.recommend_style(user_id)
                style_pct_map = {
                    "intraday": rec.allocations.intraday_pct,
                    "swing": rec.allocations.swing_pct,
                    "investing": rec.allocations.investing_pct,
                }
                style_allocation_pct = style_pct_map.get(target_style, 33.0)
                style_capital = total_capital * style_allocation_pct / 100
            except Exception as exc:
                logger.warning("recommend_style failed: %s -- using equal split", exc)
                style_allocation_pct = 33.0
                style_capital = total_capital / 3
        else:
            style_allocation_pct = 33.0
            style_capital = total_capital / 3

        result.available_capital = style_capital
        result.style_allocation_pct = style_allocation_pct

        # 3. Load instrument profile for liquidity constraints
        instrument_profile = self.profiler.get_profile(ticker)
        liquidity_cap_pct = (
            float(instrument_profile.optimal_position_size_pct)
            if instrument_profile and instrument_profile.optimal_position_size_pct
            else self.max_position_pct
        )
        result.liquidity_cap_pct = liquidity_cap_pct

        # 4. Kelly criterion
        # f* = (p·b - q) / b  where p=win_rate, q=1-p, b=win_loss_ratio
        p, q, b = win_rate, 1 - win_rate, win_loss_ratio
        kelly_raw = 0.0 if b <= 0 else (p * b - q) / b
        kelly_raw = max(0.0, kelly_raw)
        kelly_capped = min(kelly_raw * self.kelly_cap_fraction, self.max_position_pct)
        result.kelly_fraction_raw = round(kelly_raw, 4)
        result.kelly_fraction_capped = round(kelly_capped, 4)

        # 5. Apply liquidity cap
        position_pct = min(kelly_capped, liquidity_cap_pct)
        result.risk_cap_pct = max_loss_pct / 100.0

        # 6. Apply risk cap: position value x stop_loss_distance ≤ max_loss
        # Estimate stop loss from volatility (1 ATR-like proxy = avg_daily_volatility %)
        vol_pct = (
            float(instrument_profile.avg_daily_volatility) / 100.0
            if instrument_profile and instrument_profile.avg_daily_volatility
            else 0.02
        )
        stop_distance = max(vol_pct * 2, 0.01)  # 2x daily vol, min 1%
        stop_loss_price = entry_price * (1 - stop_distance * direction)
        result.stop_loss_price = round(stop_loss_price, 2)
        max_loss_idr = total_capital * max_loss_pct / 100.0
        # position_value x stop_distance ≤ max_loss_idr
        # → position_value ≤ max_loss_idr / stop_distance
        risk_cap_value = max_loss_idr / stop_distance if stop_distance > 0 else float("inf")
        result.risk_per_trade_idr = round(max_loss_idr, 2)

        # 7. Compute final position value = min(kelly, liquidity, risk, portfolio)
        kelly_value = style_capital * position_pct
        portfolio_cap_value = total_capital * self.max_position_pct
        result.portfolio_cap_pct = self.max_position_pct
        final_value = min(kelly_value, risk_cap_value, portfolio_cap_value)
        final_value = max(0.0, final_value)

        # 8. Convert to shares & lots
        if entry_price > 0:
            shares = int(final_value / entry_price)
            lots = shares // self.lot_size
            shares = lots * self.lot_size  # round down to whole lots
            value_idr = shares * entry_price
        else:
            shares = lots = 0
            value_idr = 0.0

        result.shares = shares
        result.lots = lots
        result.value_idr = round(value_idr, 2)
        result.position_pct_of_portfolio = round(
            value_idr / total_capital * 100 if total_capital > 0 else 0.0, 4
        )

        # 8b. Trading cost estimates
        if shares > 0 and entry_price > 0:
            entry_cb = self.cost_model.entry_cost(shares, entry_price)
            result.estimated_entry_cost_idr = round(entry_cb.total, 2)
            # Estimate exit at target (2x vol move) for round-trip preview
            exit_price_est = entry_price * (1 + 2 * stop_distance * direction)
            rt = self.cost_model.round_trip_cost(shares, entry_price, exit_price_est)
            result.estimated_round_trip_cost_idr = round(rt.total, 2)
            result.round_trip_cost_rate = round(
                self.cost_model.round_trip_cost_rate(), 6,
            )

        # 9. Reasoning
        result.reasoning_steps = self._build_reasoning_steps(
            ticker, direction, entry_price, total_capital, style_capital,
            style_allocation_pct, target_style, kelly_raw, kelly_capped,
            liquidity_cap_pct, max_loss_pct, stop_distance, stop_loss_price,
            max_loss_idr, risk_cap_value, portfolio_cap_value, final_value,
            shares, lots, value_idr, instrument_profile,
            result.estimated_entry_cost_idr, result.estimated_round_trip_cost_idr,
            result.round_trip_cost_rate,
        )
        result.reasoning = " | ".join(result.reasoning_steps)

        # 10. Approve/reject
        if shares == 0:
            result.approved = False
            result.rejection_reason = (
                f"Position too small -- final_value Rp {final_value:,.0f} "
                f"< 1 lot ({self.lot_size} shares x Rp {entry_price:,.0f})"
            )
        return result

    def size_multiple(
        self,
        signals: list[dict[str, Any]],
        user_id: str = "default",
        portfolio_override: float | None = None,
    ) -> list[PositionSizingResult]:
        """Size multiple positions, scaling for portfolio concentration.

        Each signal: {ticker, direction, entry_price, win_rate, win_loss_ratio, target_style}
        """
        # Sort by confidence/direction strength descending -- allocate capital
        # in order so highest-conviction gets first dibs.
        sorted_signals = sorted(
            signals,
            key=lambda s: abs(s.get("raw_position", 0.0)) + s.get("win_rate", 0.5),
            reverse=True,
        )
        # Track remaining capital per style
        user_profile = self.advisor.get_profile(user_id)
        if user_profile is None and portfolio_override is None:
            return [
                PositionSizingResult(
                    ticker=s["ticker"], direction=s.get("direction", 0),
                    approved=False, rejection_reason=f"No profile for {user_id}",
                )
                for s in sorted_signals
            ]
        total_cap = portfolio_override or (user_profile.capital if user_profile else 0)
        # Per-style remaining capital
        if user_profile is not None:
            try:
                rec = self.advisor.recommend_style(user_id)
                remaining = {
                    "intraday": rec.allocations.intraday_capital,
                    "swing": rec.allocations.swing_capital,
                    "investing": rec.allocations.investing_capital,
                }
            except Exception:
                third = total_cap / 3
                remaining = {"intraday": third, "swing": third, "investing": third}
        else:
            third = total_cap / 3
            remaining = {"intraday": third, "swing": third, "investing": third}

        results: list[PositionSizingResult] = []
        for sig in sorted_signals:
            style = sig.get("target_style", "swing")
            available = remaining.get(style, 0)
            if available <= 0:
                results.append(PositionSizingResult(
                    ticker=sig["ticker"], direction=sig.get("direction", 0),
                    approved=False, rejection_reason=f"No capital left for {style}",
                ))
                continue
            result = self.size_position(
                ticker=sig["ticker"],
                direction=sig.get("direction", 0),
                entry_price=sig.get("entry_price", 0.0),
                win_rate=sig.get("win_rate", 0.55),
                win_loss_ratio=sig.get("win_loss_ratio", 1.5),
                target_style=style,
                user_id=user_id,
                portfolio_override=available,
            )
            results.append(result)
            # Deduct allocated capital
            remaining[style] = max(0, available - result.value_idr)
        return results

    # ── helpers ─────────────────────────────────────────────────────────────

    def _build_reasoning_steps(
        self,
        ticker: str, direction: int, entry_price: float,
        total_capital: float, style_capital: float, style_pct: float,
        target_style: str,
        kelly_raw: float, kelly_capped: float,
        liquidity_cap_pct: float, max_loss_pct: float,
        stop_distance: float, stop_loss_price: float,
        max_loss_idr: float, risk_cap_value: float,
        portfolio_cap_value: float, final_value: float,
        shares: int, lots: int, value_idr: float,
        instrument_profile: InstrumentProfile | None,
        entry_cost_idr: float = 0.0,
        round_trip_cost_idr: float = 0.0,
        round_trip_cost_rate: float = 0.0,
    ) -> list[str]:
        steps: list[str] = []
        dir_str = "BUY" if direction > 0 else "SELL"
        steps.append(
            f"Modal total Rp {total_capital:,.0f}, alokasi {target_style} {style_pct:.1f}% "
            f"= Rp {style_capital:,.0f}"
        )
        steps.append(
            f"Kelly raw f*={kelly_raw:.4f}, quarter-Kelly capped={kelly_capped:.4f} "
            f"(maks {self.kelly_cap_fraction*100:.0f}% dari Kelly)"
        )
        steps.append(
            f"Liquidity cap dari profile: {liquidity_cap_pct*100:.2f}% "
            f"(optimal_position_size_pct)"
        )
        steps.append(
            f"Risk cap: max loss {max_loss_pct:.1f}% = Rp {max_loss_idr:,.0f}, "
            f"stop @ {stop_loss_price:,.0f} (jarak {stop_distance*100:.2f}%) "
            f"→ max value Rp {risk_cap_value:,.0f}"
        )
        steps.append(
            f"Portfolio cap: {self.max_position_pct*100:.1f}% = Rp {portfolio_cap_value:,.0f}"
        )
        steps.append(
            f"Final value = min(Kelly, risk, portfolio) = Rp {final_value:,.0f}"
        )
        steps.append(
            f"{dir_str} {shares} saham ({lots} lot x {self.lot_size}) @ Rp {entry_price:,.0f} "
            f"= Rp {value_idr:,.0f} ({value_idr/total_capital*100:.2f}% portofolio)"
        )
        if round_trip_cost_idr > 0:
            steps.append(
                f"Estimasi biaya: entry Rp {entry_cost_idr:,.0f}, "
                f"round-trip Rp {round_trip_cost_idr:,.0f} "
                f"(rate {round_trip_cost_rate*100:.2f}% nilai posisi)"
            )
        return steps


__all__ = [
    "CapitalAwarePositionSizer",
    "PositionSizingResult",
]
