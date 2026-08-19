"""Walk-forward backtest with DSR + PBO validation.

Runs walk-forward optimization for 5 strategy variants on top IDX tickers,
computes Deflated Sharpe Ratio and Probability of Backtest Overfitting.

Usage:
    python scripts/run_backtest.py [--tickers BBCA.JK,BBRI.JK] [--limit 10]
"""

import argparse
import json
import logging
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

from quant.core.db import get_db
from quant.backtest.walk_forward import WalkForwardOptimizer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).resolve().parent.parent / "models" / "backtest_results"


# ── Strategy functions ──────────────────────────────────────────────

def sma_crossover(close: pd.Series, fast: int = 10, slow: int = 30) -> pd.Series:
    """SMA crossover strategy."""
    sma_f = close.rolling(fast).mean()
    sma_s = close.rolling(slow).mean()
    signal = (sma_f > sma_s).astype(int) * 0.02 - 0.01  # long/flat
    log_ret = np.log(close / close.shift(1))
    return signal.shift(1) * log_ret  # lag by 1 to avoid look-ahead


def momentum(close: pd.Series, lookback: int = 20) -> pd.Series:
    """Momentum strategy."""
    signal = (close.pct_change(lookback) > 0).astype(int) * 0.02 - 0.01
    log_ret = np.log(close / close.shift(1))
    return signal.shift(1) * log_ret


def mean_reversion(close: pd.Series, lookback: int = 10) -> pd.Series:
    """Mean reversion strategy."""
    sma = close.rolling(lookback).mean()
    signal = (close < sma).astype(int) * 0.02 - 0.01  # buy when below SMA
    log_ret = np.log(close / close.shift(1))
    return signal.shift(1) * log_ret


def rsi_strategy(close: pd.Series, period: int = 14, threshold: float = 30) -> pd.Series:
    """RSI oversold strategy."""
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / (loss + 1e-8)
    rsi = 100 - (100 / (1 + rs))
    signal = (rsi < threshold).astype(int) * 0.02 - 0.01
    log_ret = np.log(close / close.shift(1))
    return signal.shift(1) * log_ret


def breakout(close: pd.Series, lookback: int = 20) -> pd.Series:
    """Donchian breakout strategy."""
    upper = close.rolling(lookback).max().shift(1)
    signal = (close > upper).astype(int) * 0.02 - 0.01
    log_ret = np.log(close / close.shift(1))
    return signal.shift(1) * log_ret


# ── Strategy configurations ─────────────────────────────────────────

STRATEGIES = {
    "sma_crossover": {
        "fn": sma_crossover,
        "params": {"fast": [5, 10, 20], "slow": [20, 30, 50]},
    },
    "momentum": {
        "fn": momentum,
        "params": {"lookback": [10, 20, 60]},
    },
    "mean_reversion": {
        "fn": mean_reversion,
        "params": {"lookback": [5, 10, 20]},
    },
    "rsi_oversold": {
        "fn": rsi_strategy,
        "params": {"period": [7, 14], "threshold": [25, 30, 35]},
    },
    "breakout": {
        "fn": breakout,
        "params": {"lookback": [10, 20, 55]},
    },
}


def load_ticker_data(session, ticker: str, end_date: date, lookback_days: int = 800) -> pd.Series:
    """Load close prices for a ticker."""
    start_date = end_date - timedelta(days=lookback_days)
    result = session.execute(text(
        "SELECT date, close FROM stock_prices WHERE ticker = :ticker "
        "AND date BETWEEN :start AND :end ORDER BY date"
    ), {"ticker": ticker, "start": start_date, "end": end_date})
    rows = result.fetchall()
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows, columns=["date", "close"])
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = df["close"].astype(float)
    return df.set_index("date")["close"]


def main():
    parser = argparse.ArgumentParser(description="Walk-forward backtest with DSR+PBO")
    parser.add_argument("--tickers", type=str, default=None)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--train-days", type=int, default=252)
    parser.add_argument("--test-days", type=int, default=63)
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    session = get_db()

    # Get tickers
    if args.tickers:
        tickers = args.tickers.split(",")
    else:
        result = session.execute(text(
            "SELECT ticker, count(*) as cnt FROM stock_prices "
            "WHERE ticker LIKE '%%.JK' AND ticker NOT LIKE 'IDX%%' "
            "GROUP BY ticker HAVING count(*) >= 400 ORDER BY cnt DESC LIMIT :limit"
        ), {"limit": args.limit})
        tickers = [r[0] for r in result.fetchall()]

    logger.info("Backtesting %d tickers: %s", len(tickers), tickers)
    end_date = date(2026, 8, 18)

    wfo = WalkForwardOptimizer(
        train_days=args.train_days,
        test_days=args.test_days,
        embargo_days=5,
    )

    all_results = {}

    for ticker in tickers:
        close = load_ticker_data(session, ticker, end_date)
        if len(close) < args.train_days + args.test_days:
            logger.warning("Insufficient data for %s: %d rows", ticker, len(close))
            continue

        logger.info("Backtesting %s (%d rows)...", ticker, len(close))
        ticker_results = {}

        for strat_name, strat_config in STRATEGIES.items():
            try:
                result = wfo.run_with_validation(
                    close=close,
                    strategy_fn=strat_config["fn"],
                    param_grid=strat_config["params"],
                    metric="sharpe",
                    n_trials=len(STRATEGIES),
                    n_pbo_partitions=16,
                )

                ticker_results[strat_name] = {
                    "oos_sharpe": round(result.oos_sharpe, 3) if np.isfinite(result.oos_sharpe) else None,
                    "oos_return_pct": round(result.oos_total_return * 100, 2),
                    "oos_max_drawdown_pct": round(result.oos_max_drawdown * 100, 2),
                    "param_stability": round(result.param_stability, 3),
                    "n_splits": len(result.windows),
                    "dsr": round(result.dsr, 4),
                    "dsr_psr": round(result.dsr_psr, 4),
                    "pbo": round(result.pbo, 4),
                    "pbo_is_overfit": result.pbo_is_overfit,
                    "is_statistically_valid": result.is_statistically_valid,
                    "best_params_per_fold": result.best_params_per_fold,
                }

                logger.info(
                    "  %s: OOS Sharpe=%.2f, return=%.2f%%, DSR=%.4f, PBO=%.4f, valid=%s",
                    strat_name,
                    result.oos_sharpe if np.isfinite(result.oos_sharpe) else 0,
                    result.oos_total_return * 100,
                    result.dsr,
                    result.pbo,
                    result.is_statistically_valid,
                )
            except Exception as e:
                logger.warning("  %s failed: %s", strat_name, e)
                ticker_results[strat_name] = {"error": str(e)}

        all_results[ticker] = ticker_results

    # Save results
    report_path = RESULTS_DIR / "walk_forward_report.json"
    with open(report_path, "w") as f:
        json.dump({
            "date": str(date.today()),
            "tickers": tickers,
            "train_days": args.train_days,
            "test_days": args.test_days,
            "results": all_results,
        }, f, indent=2, default=str)

    # Print summary
    print("\n" + "=" * 80)
    print("WALK-FORWARD BACKTEST SUMMARY")
    print("=" * 80)

    # Aggregate by strategy
    strat_summary = {}
    for ticker, ticker_res in all_results.items():
        for strat, res in ticker_res.items():
            if "error" in res:
                continue
            if strat not in strat_summary:
                strat_summary[strat] = {"sharpe": [], "return": [], "dsr": [], "pbo": [], "valid": 0, "total": 0}
            if res["oos_sharpe"] is not None:
                strat_summary[strat]["sharpe"].append(res["oos_sharpe"])
            strat_summary[strat]["return"].append(res["oos_return_pct"])
            strat_summary[strat]["dsr"].append(res["dsr"])
            strat_summary[strat]["pbo"].append(res["pbo"])
            strat_summary[strat]["total"] += 1
            if res["is_statistically_valid"]:
                strat_summary[strat]["valid"] += 1

    print(f"\n{'Strategy':<20} {'Avg Sharpe':>12} {'Avg Return%':>12} {'Avg DSR':>10} {'Avg PBO':>10} {'Valid/Total':>12}")
    print("-" * 80)
    for strat, s in sorted(strat_summary.items(), key=lambda x: np.mean(x[1]["sharpe"]) if x[1]["sharpe"] else -999, reverse=True):
        avg_sharpe = np.mean(s["sharpe"]) if s["sharpe"] else 0
        avg_ret = np.mean(s["return"]) if s["return"] else 0
        avg_dsr = np.mean(s["dsr"]) if s["dsr"] else 0
        avg_pbo = np.mean(s["pbo"]) if s["pbo"] else 0
        print(f"{strat:<20} {avg_sharpe:>12.3f} {avg_ret:>12.2f} {avg_dsr:>10.4f} {avg_pbo:>10.4f} {s['valid']:>5}/{s['total']:<5}")

    print(f"\nResults saved to: {report_path}")
    session.close()


if __name__ == "__main__":
    main()
