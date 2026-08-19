"""Compute features for top liquid IDX tickers and store in DB."""

from __future__ import annotations

import time
from datetime import date

from sqlalchemy import text

from quant.core.db import get_db
from quant.features.factor_library import FactorLibrary


def main():
    session = get_db()
    lib = FactorLibrary(session=session)
    lib.register_default_factors()

    # Get top 50 most liquid tickers by recent volume
    result = session.execute(text(
        "SELECT ticker, avg(volume) as avg_vol "
        "FROM stock_prices "
        "WHERE date >= '2026-07-01' AND volume > 0 "
        "GROUP BY ticker "
        "ORDER BY avg_vol DESC "
        "LIMIT 50"
    ))
    tickers = [r[0] for r in result.fetchall()]
    print(f"Computing features for {len(tickers)} tickers...")

    as_of = date(2026, 8, 19)
    factor_names = lib.factor_names
    total_computed = 0
    start_time = time.time()

    for i, ticker in enumerate(tickers):
        t_start = time.time()
        count = 0
        for fname in factor_names:
            val = lib.compute_and_store(fname, ticker, as_of)
            if val is not None:
                count += 1
        total_computed += count
        elapsed = time.time() - t_start
        if (i + 1) % 10 == 0 or i == 0:
            print(f"  [{i+1}/{len(tickers)}] {ticker}: {count}/{len(factor_names)} factors ({elapsed:.1f}s)")

    total_elapsed = time.time() - start_time
    print(f"\nTotal: {total_computed} feature values computed in {total_elapsed:.1f}s")

    # Verify
    rows = session.execute(text("SELECT count(*) FROM feature_values")).scalar()
    defs = session.execute(text("SELECT count(*) FROM feature_definitions")).scalar()
    tickers_stored = session.execute(text("SELECT count(DISTINCT ticker) FROM feature_values")).scalar()
    print(f"feature_definitions: {defs}, feature_values: {rows}, tickers: {tickers_stored}")

    lib.close()
    session.close()


if __name__ == "__main__":
    main()
