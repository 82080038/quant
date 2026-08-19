"""Fix sector & industry mapping for IDX instruments using yfinance.

Fetches sector and industry from Yahoo Finance for all IDX equity tickers,
maps Yahoo sectors to IDX sector_master IDs, and stores both sector_id
and industry/sub_industry in the instruments table.

Uses dynamic rate limiting: starts at 2s delay, adjusts based on
response success/failure.

Usage:
    python scripts/fix_sector_mapping.py [--dry-run] [--batch-size 50] [--limit 20]
"""

import argparse
import logging
import time
from collections import Counter

import yfinance as yf
from sqlalchemy import text

from quant.core.db import get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Yahoo Finance sector → IDX sector_master ID mapping
YAHOO_TO_IDX_SECTOR = {
    "Financial Services": 10,          # Financials
    "Energy": 6,                       # Mining (includes oil & gas)
    "Basic Materials": 7,              # Basic Industry
    "Consumer Cyclical": 8,            # Cyclical Consumer Goods
    "Consumer Defensive": 9,           # Non-Cyclical Consumer Goods
    "Real Estate": 11,                 # Property & Real Estate
    "Industrials": 12,                 # Infrastructure
    "Communication Services": 12,      # Infrastructure (telecom)
    "Utilities": 12,                   # Infrastructure (utilities)
    "Technology": 13,                  # Technology
    "Healthcare": 14,                  # Healthcare
    "Materials": 7,                    # Basic Industry
    "Agriculture": 5,                  # Agriculture
    "Miscellaneous": 15,               # Miscellaneous
    "N/A": 15,                         # Fallback
}

IDX_SECTOR_NAMES = {
    5: "Agriculture",
    6: "Mining",
    7: "Basic Industry",
    8: "Cyclical Consumer Goods",
    9: "Non-Cyclical Consumer Goods",
    10: "Financials",
    11: "Property & Real Estate",
    12: "Infrastructure",
    13: "Technology",
    14: "Healthcare",
    15: "Miscellaneous",
}


class DynamicRateLimiter:
    """Adaptive rate limiter — speeds up on success, slows down on errors."""

    def __init__(
        self,
        initial_delay: float = 2.0,
        min_delay: float = 0.3,
        max_delay: float = 10.0,
        speed_up_factor: float = 0.8,
        slow_down_factor: float = 1.5,
    ):
        self.delay = initial_delay
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.speed_up_factor = speed_up_factor
        self.slow_down_factor = slow_down_factor
        self._consecutive_ok = 0
        self._consecutive_err = 0

    def on_success(self):
        self._consecutive_ok += 1
        self._consecutive_err = 0
        if self._consecutive_ok >= 3:
            self.delay = max(self.min_delay, self.delay * self.speed_up_factor)
            self._consecutive_ok = 0

    def on_error(self):
        self._consecutive_err += 1
        self._consecutive_ok = 0
        self.delay = min(self.max_delay, self.delay * self.slow_down_factor)

    def wait(self):
        time.sleep(self.delay)


def fetch_sector_from_yahoo(ticker: str) -> tuple[str | None, str | None, str | None]:
    """Fetch sector, industry from yfinance.

    Returns:
        (yahoo_sector, industry, sub_industry) or (None, None, None).
    """
    try:
        info = yf.Ticker(ticker).get_info()
        sector = info.get("sector")
        industry = info.get("industry")
        sub_industry = info.get("industryDisplayName") or info.get("sectorDisplayName")
        return sector, industry, sub_industry
    except Exception as e:
        logger.debug("yfinance error for %s: %s", ticker, e)
        return None, None, None


def main():
    parser = argparse.ArgumentParser(description="Fix sector & industry mapping via yfinance")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    parser.add_argument("--batch-size", type=int, default=50, help="Commit every N updates")
    parser.add_argument("--limit", type=int, default=None, help="Limit tickers (for testing)")
    args = parser.parse_args()

    session = get_db()

    # Get all IDX equity tickers
    result = session.execute(text("""
        SELECT ticker, company_name, sector_id, industry
        FROM instruments
        WHERE ticker LIKE '%%.JK' AND ticker NOT LIKE 'IDX%%'
        ORDER BY ticker
    """))
    all_tickers = result.fetchall()
    if args.limit:
        all_tickers = all_tickers[:args.limit]
    logger.info("Processing %d IDX equity tickers", len(all_tickers))

    limiter = DynamicRateLimiter(initial_delay=2.0, min_delay=0.3, max_delay=10.0)
    results: dict[str, dict] = {}
    errors = 0
    fetched = 0
    skipped = 0

    for i, row in enumerate(all_tickers):
        ticker, company_name, old_sector, old_industry = row

        # Skip if already has proper sector (not 5/Agriculture default) and industry
        if old_sector and old_sector != 5 and old_industry:
            results[ticker] = {
                "sector_id": old_sector,
                "industry": old_industry,
                "sub_industry": "",
                "source": "existing",
            }
            skipped += 1
            continue

        limiter.wait()
        yahoo_sector, industry, sub_industry = fetch_sector_from_yahoo(ticker)

        if yahoo_sector:
            sector_id = YAHOO_TO_IDX_SECTOR.get(yahoo_sector, 15)
            results[ticker] = {
                "sector_id": sector_id,
                "industry": industry or "",
                "sub_industry": sub_industry or "",
                "yahoo_sector": yahoo_sector,
                "source": "yfinance",
            }
            limiter.on_success()
            fetched += 1
        else:
            errors += 1
            limiter.on_error()
            results[ticker] = {
                "sector_id": old_sector or 15,
                "industry": old_industry or "",
                "sub_industry": "",
                "source": "fallback",
            }

        # Progress log
        if (i + 1) % 50 == 0:
            logger.info(
                "Progress: %d/%d (fetched=%d, skipped=%d, errors=%d, delay=%.1fs)",
                i + 1, len(all_tickers), fetched, skipped, errors, limiter.delay,
            )

        # Batch commit
        if not args.dry_run and (i + 1) % args.batch_size == 0:
            _commit_batch(session, results, len(results) - args.batch_size, len(results))
            session.commit()
            logger.info("Committed batch at %d/%d", i + 1, len(all_tickers))

    # Final commit
    if not args.dry_run:
        _commit_batch(session, results, 0, len(results))
        session.commit()
        logger.info("All changes committed to DB")

    # Summary
    print("\n" + "=" * 70)
    print("SECTOR & INDUSTRY MAPPING SUMMARY")
    print("=" * 70)

    source_counts = Counter(v["source"] for v in results.values())
    print(f"\nData source:")
    for src, cnt in source_counts.most_common():
        print(f"  {src:15s}: {cnt}")

    sector_counts = Counter(v["sector_id"] for v in results.values())
    print(f"\nSector distribution:")
    for sid, cnt in sorted(sector_counts.items()):
        name = IDX_SECTOR_NAMES.get(sid, f"Unknown({sid})")
        bar = "#" * (cnt // 10)
        print(f"  {name:30s} (id={sid:2d}): {cnt:4d}  {bar}")

    industry_counts = Counter(v["industry"] for v in results.values() if v["industry"])
    print(f"\nTop 25 industries ({len(industry_counts)} total):")
    for ind, cnt in industry_counts.most_common(25):
        print(f"  {ind:50s}: {cnt:4d}")

    print(f"\nFetched from yfinance: {fetched}")
    print(f"Skipped (already mapped): {skipped}")
    print(f"Errors (fallback): {errors}")
    print(f"Final rate limiter delay: {limiter.delay:.1f}s")

    # Show sample changes
    print("\nSample sector changes (first 25):")
    changes = 0
    for row in all_tickers:
        ticker, company_name, old_sector, old_industry = row
        new = results.get(ticker)
        if new and new["sector_id"] != old_sector:
            changes += 1
            if changes <= 25:
                old_name = IDX_SECTOR_NAMES.get(old_sector, "?")
                new_name = IDX_SECTOR_NAMES.get(new["sector_id"], "?")
                ind = new["industry"] or "—"
                print(f"  {ticker:12s} {old_name:25s} → {new_name:25s} industry={ind}")

    print(f"\nTotal sector changes: {changes}")

    if args.dry_run:
        print("\n[DRY RUN] No changes written to DB")

    session.close()


def _commit_batch(session, results: dict, start: int, end: int) -> None:
    """Commit a batch of results to DB."""
    items = list(results.items())[start:end]
    for ticker, info in items:
        session.execute(text("""
            UPDATE instruments
            SET sector_id = :sid, industry = :ind, sub_industry = :sub,
                updated_at = now()
            WHERE ticker = :ticker
        """), {
            "sid": info["sector_id"],
            "ind": info["industry"],
            "sub": info["sub_industry"],
            "ticker": ticker,
        })


if __name__ == "__main__":
    main()
