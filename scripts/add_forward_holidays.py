"""Add forward-looking holidays for next 30+ days."""
from sqlalchemy import text
from quant.core.db import get_db

session = get_db()

# Get exchange IDs
exchanges = {}
result = session.execute(text("SELECT mic, id FROM exchanges WHERE is_active = TRUE"))
for r in result:
    exchanges[r[0]] = r[1]

forward_holidays = [
    ("XIDX", "2026-09-19", "Maulid Nabi Muhammad SAW", False),
    ("XTSE", "2026-09-21", "Respect for the Aged Day", False),
    ("XTSE", "2026-09-23", "Autumnal Equinox Day", False),
    ("XHKG", "2026-09-16", "Day After Mid-Autumn Festival", False),
    ("XSHG", "2026-09-16", "Mid-Autumn Festival", False),
    ("XSHG", "2026-09-17", "Mid-Autumn Festival", False),
    ("XFRA", "2026-10-03", "German Unity Day", False),
]

inserted = 0
for mc, hdate, hname, is_hist in forward_holidays:
    eid = exchanges.get(mc)
    if not eid:
        continue
    try:
        session.execute(text(
            "INSERT INTO market_holidays (exchange_id, market_code, holiday_date, holiday_name, is_historical) "
            "VALUES (:eid, :mc, :hd, :hn, :ih) "
            "ON CONFLICT (exchange_id, holiday_date, holiday_name) DO NOTHING"
        ), {"eid": eid, "mc": mc, "hd": hdate, "hn": hname, "ih": is_hist})
        inserted += 1
    except Exception as e:
        print(f"Error: {e}")

session.commit()

# Verify
result = session.execute(text(
    "SELECT market_code, holiday_date, holiday_name, is_historical "
    "FROM market_holidays WHERE holiday_date >= '2026-08-21' "
    "ORDER BY holiday_date, market_code"
))
print("Forward holidays (after 2026-08-20):")
for r in result:
    print(f"  {r[0]:8s} {r[1]} {r[2]:40s} hist={r[3]}")

print(f"\nInserted: {inserted}")
session.close()
