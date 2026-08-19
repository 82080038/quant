"""Run the daily pipeline end-to-end."""

import json
import logging
import sys
from datetime import date

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from quant.pipeline.orchestrator import PipelineOrchestrator

as_of = date(2026, 8, 19)
universe_limit = int(sys.argv[1]) if len(sys.argv) > 1 else 50

orch = PipelineOrchestrator()
try:
    summary = orch.run_daily(as_of, universe_limit=universe_limit)
    print("\n" + "=" * 60)
    print("PIPELINE SUMMARY")
    print("=" * 60)
    print(json.dumps(summary, indent=2, default=str))

    # Show pipeline state from DB
    from sqlalchemy import text
    states = orch.session.execute(text(
        "SELECT step, status, count(*) FROM pipeline_state "
        "WHERE date = :date GROUP BY step, status ORDER BY step, status"
    ), {"date": as_of}).fetchall()
    print("\nPipeline state breakdown:")
    for step, status, count in states:
        print(f"  {step:12s} {status:25s} {count}")

    # Show signal attribution
    sig_count = orch.session.execute(text(
        "SELECT count(*) FROM signal_attribution_log WHERE date = :date"
    ), {"date": as_of}).scalar()
    print(f"\nSignal attribution log: {sig_count} entries")

    # Show portfolio weights
    pw = orch.session.execute(text(
        "SELECT ticker, weight FROM portfolio_weights WHERE date = :date ORDER BY weight DESC"
    ), {"date": as_of}).fetchall()
    if pw:
        print(f"\nPortfolio weights ({len(pw)} positions):")
        for ticker, weight in pw:
            print(f"  {ticker:15s} {float(weight):.4f}")

finally:
    orch.close()
