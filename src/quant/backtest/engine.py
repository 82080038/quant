"""Event-driven backtest engine (pustaka/29, pustaka/85).

Executes strategies on historical OHLCV data with realistic costs:
- Next-bar-open execution (no look-ahead bias)
- IDX transaction costs: commission 0.15%, sales tax 0.1%
- Slippage model: proportional to order size vs ADV

Returns equity curve, trade log, and performance metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quant.backtest.strategies import Signal, Strategy


@dataclass
class Trade:
    """A single executed trade."""

    date: pd.Timestamp
    ticker: str
    side: str  # "buy" or "sell"
    price: float
    shares: int
    cost: float  # transaction cost in IDR


@dataclass
class BacktestResult:
    """Backtest performance result."""

    equity_curve: pd.Series
    trades: list[Trade] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)


# IDX transaction cost constants
COMMISSION_RATE = 0.0015  # 0.15%
SALES_TAX_RATE = 0.001  # 0.1% (only on sell)
SLIPPAGE_RATE = 0.0005  # 0.05%


class BacktestEngine:
    """Event-driven backtest engine with realistic execution."""

    def __init__(
        self,
        initial_capital: float = 100_000_000,  # 100M IDR
        commission_rate: float = COMMISSION_RATE,
        sales_tax_rate: float = SALES_TAX_RATE,
        slippage_rate: float = SLIPPAGE_RATE,
        max_position_pct: float = 1.0,  # Max fraction of capital per trade
    ) -> None:
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.sales_tax_rate = sales_tax_rate
        self.slippage_rate = slippage_rate
        self.max_position_pct = max_position_pct

    def run(
        self,
        strategy: Strategy,
        data: pd.DataFrame,
        ticker: str = "ASSET",
        n_trials: int = 1,
    ) -> BacktestResult:
        """Run backtest on historical data.

        Args:
            strategy: Strategy instance with generate_signals method.
            data: OHLCV DataFrame with columns: open, high, low, close, volume.
            ticker: Asset ticker for trade logging.
            n_trials: Number of strategies tested in this experiment
                (for Deflated Sharpe Ratio multiple-testing correction).
                Default 1 = no multiple-testing adjustment.

        Returns:
            BacktestResult with equity curve, trades, and metrics.
        """
        if data.empty:
            return BacktestResult(
                equity_curve=pd.Series(dtype=float),
                trades=[],
                metrics={},
            )

        signals = strategy.generate_signals(data)

        cash = self.initial_capital
        shares = 0
        equity_curve: list[float] = []
        trades: list[Trade] = []

        for i in range(len(data)):
            data.index[i]
            signal = signals.iloc[i] if i < len(signals) else Signal.HOLD

            # Execute at next bar's open (avoid look-ahead)
            if i + 1 < len(data) and signal != Signal.HOLD:
                exec_date = data.index[i + 1]
                exec_price = float(data["open"].iloc[i + 1])

                # Apply slippage
                if signal == Signal.BUY:
                    exec_price *= (1 + self.slippage_rate)
                else:
                    exec_price *= (1 - self.slippage_rate)

                if signal == Signal.BUY and cash > 0:
                    # Buy with position sizing limit (reserve for commission)
                    deployable = cash * self.max_position_pct
                    max_value = deployable / (1 + self.commission_rate)
                    shares_to_buy = int(max_value / exec_price)
                    # IDX lot size = 100
                    shares_to_buy = (shares_to_buy // 100) * 100

                    if shares_to_buy > 0:
                        trade_value = shares_to_buy * exec_price
                        commission = trade_value * self.commission_rate
                        total_cost = trade_value + commission

                        if total_cost <= cash:
                            cash -= total_cost
                            shares += shares_to_buy
                            trades.append(
                                Trade(
                                    date=exec_date,
                                    ticker=ticker,
                                    side="buy",
                                    price=exec_price,
                                    shares=shares_to_buy,
                                    cost=commission,
                                ),
                            )

                elif signal == Signal.SELL and shares > 0:
                    trade_value = shares * exec_price
                    commission = trade_value * self.commission_rate
                    sales_tax = trade_value * self.sales_tax_rate
                    net_proceeds = trade_value - commission - sales_tax

                    cash += net_proceeds
                    trades.append(
                        Trade(
                            date=exec_date,
                            ticker=ticker,
                            side="sell",
                            price=exec_price,
                            shares=shares,
                            cost=commission + sales_tax,
                        ),
                    )
                    shares = 0

            # Mark-to-market
            close_price = float(data["close"].iloc[i])
            equity = cash + shares * close_price
            equity_curve.append(equity)

        equity_series = pd.Series(
            equity_curve, index=data.index[:len(equity_curve)],
        )

        metrics = self._compute_metrics(equity_series, trades, n_trials=n_trials)

        return BacktestResult(
            equity_curve=equity_series,
            trades=trades,
            metrics=metrics,
        )

    def _compute_metrics(
        self,
        equity: pd.Series,
        trades: list[Trade] | None = None,
        n_trials: int = 1,
    ) -> dict[str, float]:
        """Compute performance metrics from equity curve.

        Args:
            equity: Mark-to-market equity curve.
            trades: Optional list of executed trades for win-rate calc.
            n_trials: Number of strategies tested in this experiment
                (for Deflated Sharpe Ratio). Default 1 = no adjustment.
        """
        if equity.empty or len(equity) < 2:
            return {}

        returns = equity.pct_change(fill_method=None).dropna()

        total_return = (
            (equity.iloc[-1] / equity.iloc[0]) - 1
        ) * 100

        # Annualized return (252 trading days)
        n_days = len(equity)
        annual_return = (
            (equity.iloc[-1] / equity.iloc[0]) ** (252 / n_days) - 1
        ) * 100

        # Sharpe ratio (risk-free = 0)
        sharpe = float(returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0.0

        # Sortino ratio (downside deviation only)
        downside = returns[returns < 0]
        if len(downside) > 0 and downside.std() > 0:
            sortino = float(
                returns.mean() / downside.std() * np.sqrt(252),
            )
        else:
            sortino = 0.0

        # Max drawdown
        running_max = equity.cummax()
        drawdown = (equity - running_max) / running_max
        max_dd = float(drawdown.min() * 100)

        # Win rate from completed round-trip trades
        n_trades = 0
        win_rate = 0.0
        if trades:
            n_trades = len(trades)
            # Pair buy/sell trades to compute profitability
            buys = [t for t in trades if t.side == "buy"]
            sells = [t for t in trades if t.side == "sell"]
            wins = 0
            for i, sell in enumerate(sells):
                if i < len(buys):
                    buy = buys[i]
                    if sell.price * sell.shares > buy.price * buy.shares:
                        wins += 1
            if sells:
                win_rate = wins / len(sells) * 100

        # Deflated Sharpe Ratio (Bailey & López de Prado 2014)
        # Adjusts Sharpe for multiple-testing bias and non-normality.
        # Lazy import to avoid circular dependency (analysis imports engine).
        dsr = 0.0
        if n_trials > 1 and len(returns) >= 2 and returns.std() > 0:
            try:
                from quant.backtest.analysis import deflated_sharpe_ratio

                skew_val = float(returns.skew()) if len(returns) >= 3 else 0.0
                kurt_val = float(returns.kurtosis()) + 3.0 if len(returns) >= 4 else 3.0
                dsr = deflated_sharpe_ratio(
                    sharpe=sharpe,
                    n_trials=n_trials,
                    sample_size=len(returns),
                    skewness=skew_val,
                    kurtosis=kurt_val,
                )
            except Exception:
                # DSR is best-effort — never fail backtest on DSR error
                dsr = 0.0

        return {
            "total_return_pct": round(total_return, 2),
            "annual_return_pct": round(annual_return, 2),
            "sharpe_ratio": round(sharpe, 3),
            "deflated_sharpe_ratio": round(dsr, 4),
            "sortino_ratio": round(sortino, 3),
            "max_drawdown_pct": round(max_dd, 2),
            "win_rate_pct": round(win_rate, 2),
            "final_equity": round(float(equity.iloc[-1]), 2),
            "n_trades": n_trades,
        }

    def run_walk_forward(
        self,
        strategy: Strategy,
        data: pd.DataFrame,
        ticker: str = "ASSET",
        train_days: int = 252,
        test_days: int = 63,
    ) -> dict:
        """Run walk-forward backtest with purged train/test splits.

        Uses WalkForwardOptimizer to split data into consecutive
        (train, test) folds. Strategy is fit on train, evaluated on test.
        Returns stitched OOS metrics.

        Args:
            strategy: Strategy with optional fit() method.
            data: OHLCV DataFrame.
            ticker: Asset ticker.
            train_days: Training window length (default 252 = 1 year).
            test_days: Test window length (default 63 = 1 quarter).

        Returns:
            Dict with oos_sharpe, oos_return_pct, consistency_pct, n_splits.
        """
        from quant.analysis.walk_forward import WalkForwardOptimizer

        wfo = WalkForwardOptimizer(train_days=train_days, test_days=test_days)
        wf_result = wfo.run(
            data=data,
            strategy_fn=lambda df: strategy.generate_signals(df),
        )

        return {
            "oos_sharpe": wf_result.oos_sharpe,
            "oos_return_pct": wf_result.oos_return_pct,
            "consistency_pct": wf_result.consistency_pct,
            "n_splits": wf_result.n_splits,
            "per_fold_results": wf_result.per_fold,
        }
