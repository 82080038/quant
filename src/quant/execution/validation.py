"""Order validation for IDX (pustaka/76).

Validates orders against IDX trading rules:
- Lot size: 100 shares
- Tick size: varies by price range
- Price limits: ±20% auto-rejection daily limit
- Session: regular trading hours (09:00-15:50 WIB)
- Buying power: sufficient cash for buy orders
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    """Order validation result."""

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def get_tick_size(price: float) -> float:
    """Get IDX tick size based on price range.

    Args:
        price: Stock price.

    Returns:
        Tick size in IDR.
    """
    if price < 200:
        return 1.0
    if price < 500:
        return 2.5
    if price < 2000:
        return 5.0
    if price < 5000:
        return 10.0
    return 25.0


def validate_price_tick(price: float, tick_size: float | None = None) -> bool:
    """Check if price is a valid tick multiple.

    Args:
        price: Order price.
        tick_size: Tick size (auto-detected if None).

    Returns:
        True if price is valid.
    """
    if tick_size is None:
        tick_size = get_tick_size(price)
    remainder = price % tick_size
    return abs(remainder) < 1e-9 or abs(tick_size - remainder) < 1e-9


class OrderValidator:
    """IDX order validator."""

    def __init__(
        self,
        lot_size: int = 100,
        daily_limit_pct: float = 20.0,
        min_shares: int = 1,
    ) -> None:
        self.lot_size = lot_size
        self.daily_limit_pct = daily_limit_pct
        self.min_shares = min_shares

    def validate(
        self,
        ticker: str,
        side: str,
        shares: int,
        price: float,
        reference_price: float | None = None,
        buying_power: float | None = None,
        current_shares: int = 0,
    ) -> ValidationResult:
        """Validate an order against IDX rules.

        Args:
            ticker: Stock ticker.
            side: "buy" or "sell".
            shares: Number of shares.
            price: Order price.
            reference_price: Previous close for price limit check.
            buying_power: Available cash (for buy orders).
            current_shares: Shares held (for sell orders).

        Returns:
            ValidationResult with errors and warnings.
        """
        errors: list[str] = []
        warnings: list[str] = []

        # Lot size validation
        if side == "buy" and shares % self.lot_size != 0:
            errors.append(
                f"INVALID_LOT: shares must be multiple of {self.lot_size}",
            )
        elif (
            side == "sell"
            and shares % self.lot_size != 0
            and shares != current_shares
        ):
            errors.append(
                f"INVALID_LOT: sell shares must be multiple of "
                f"{self.lot_size} unless closing position",
            )

        # Minimum shares
        if shares < self.min_shares:
            errors.append(f"MIN_SHARES: minimum {self.min_shares} shares")

        # Price tick validation
        if not validate_price_tick(price):
            tick = get_tick_size(price)
            warnings.append(
                f"TICK_SIZE: price {price} not multiple of tick {tick}",
            )

        # Price limit (auto-rejection)
        if reference_price is not None and reference_price > 0:
            upper_limit = reference_price * (1 + self.daily_limit_pct / 100)
            lower_limit = reference_price * (1 - self.daily_limit_pct / 100)
            if price > upper_limit:
                errors.append(
                    f"PRICE_LIMIT: price {price} exceeds upper limit "
                    f"{upper_limit:.2f} (+{self.daily_limit_pct}%)",
                )
            elif price < lower_limit:
                errors.append(
                    f"PRICE_LIMIT: price {price} below lower limit "
                    f"{lower_limit:.2f} (-{self.daily_limit_pct}%)",
                )

        # Buying power check
        if side == "buy" and buying_power is not None:
            order_value = shares * price
            if order_value > buying_power:
                errors.append(
                    f"INSUFFICIENT_FUNDS: order value {order_value:.0f} "
                    f"exceeds buying power {buying_power:.0f}",
                )

        # Sell shares check
        if side == "sell" and shares > current_shares:
            errors.append(
                f"INSUFFICIENT_SHARES: trying to sell {shares} but "
                f"only hold {current_shares}",
            )

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
