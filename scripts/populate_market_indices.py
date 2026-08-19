"""Create and populate market_indices table — maps exchanges to their major indices."""

import logging
from sqlalchemy import text
from quant.core.db import get_db

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# Major index mapping: (market_code, index_symbol, index_name, yahoo_ticker, display_priority)
INDICES = [
    # IDX — Indonesia
    ("XIDX", "IHSG", "Jakarta Composite Index", "IDXCOMPOSITE.JK", 1),
    # XNYS/XNAS — US
    ("XNYS", "GSPC", "S&P 500", "^GSPC", 1),
    ("XNYS", "DJI", "Dow Jones Industrial Avg", "^DJI", 2),
    ("XNAS", "NDX", "NASDAQ 100", "^NDX", 1),
    # XTSE — Japan
    ("XTSE", "N225", "Nikkei 225", "^N225", 1),
    # XLON — UK
    ("XLON", "FTSE", "FTSE 100", "^FTSE", 1),
    # XHKG — Hong Kong
    ("XHKG", "HSI", "Hang Seng Index", "^HSI", 1),
    # XFRA — Germany
    ("XFRA", "GDAXI", "DAX", "^GDAXI", 1),
    # XSHG — China
    ("XSHG", "SSEC", "Shanghai Composite", "000001.SS", 1),
    # XKRX — Korea
    ("XKRX", "KS11", "KOSPI", "^KS11", 1),
    # XASX — Australia
    ("XASX", "AXJO", "ASX 200", "^AXJO", 1),
    # XBOM — India
    ("XBOM", "BSESN", "BSE Sensex", "^BSESN", 1),
    # BVMF — Brazil
    ("BVMF", "BVSP", "Bovespa", "^BVSP", 1),
    # XTSX — Canada
    ("XTSX", "GSPTSE", "S&P/TSX Composite", "^GSPTSE", 1),
    # XJSE — South Africa
    ("XJSE", "JNJO", "JSE Top 40", "^JNJO.JO", 1),
    # XSAU — Saudi
    ("XSAU", "TASI", "Tadawul All Share", "^TASI.SR", 1),
    # XBKK — Thailand
    ("XBKK", "SETI", "SET Index", "^SET.BK", 1),
    # XPHS — Philippines
    ("XPHS", "PSEI", "PSEi Composite", "^PSEI.PS", 1),
    # XTAI — Taiwan
    ("XTAI", "TWII", "Taiex", "^TWII", 1),
    # XKLSE — Malaysia
    ("XKLSE", "KLSE", "FTSE Bursa Malaysia KLCI", "^KLSE", 1),
    # XSGX — Singapore
    ("XSGX", "STI", "Straits Times Index", "^STI", 1),
    # XPAR — France
    ("XPAR", "FCHI", "CAC 40", "^FCHI", 1),
    # XMAD — Spain
    ("XMAD", "IBEX", "IBEX 35", "^IBEX", 1),
]


def main():
    session = get_db()

    log.info("Creating market_indices table...")
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS market_indices (
            id SERIAL PRIMARY KEY,
            exchange_id INTEGER REFERENCES exchanges(id) ON DELETE CASCADE,
            market_code VARCHAR(10) NOT NULL,
            index_symbol VARCHAR(20) NOT NULL,
            index_name VARCHAR(200) NOT NULL,
            yahoo_ticker VARCHAR(50),
            display_priority INTEGER DEFAULT 1,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT now(),
            UNIQUE (market_code, index_symbol)
        )
    """))
    session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_market_indices_market
        ON market_indices (market_code, is_active)
    """))
    session.commit()

    # Get exchange IDs
    exchanges = {}
    result = session.execute(text("SELECT mic, id FROM exchanges WHERE is_active = TRUE"))
    for r in result:
        exchanges[r[0]] = r[1]

    inserted = 0
    for mc, sym, name, yticker, prio in INDICES:
        eid = exchanges.get(mc)
        if not eid:
            log.warning("No exchange %s — skipping %s", mc, sym)
            continue
        try:
            session.execute(text("""
                INSERT INTO market_indices (exchange_id, market_code, index_symbol, index_name, yahoo_ticker, display_priority, is_active)
                VALUES (:eid, :mc, :sym, :name, :yt, :prio, TRUE)
                ON CONFLICT (market_code, index_symbol) DO UPDATE SET
                    index_name = EXCLUDED.index_name,
                    yahoo_ticker = EXCLUDED.yahoo_ticker,
                    display_priority = EXCLUDED.display_priority
            """), {"eid": eid, "mc": mc, "sym": sym, "name": name, "yt": yticker, "prio": prio})
            inserted += 1
        except Exception as e:
            log.error("Failed for %s/%s: %s", mc, sym, e)

    session.commit()

    # Verify
    result = session.execute(text("""
        SELECT mi.market_code, mi.index_symbol, mi.index_name, mi.yahoo_ticker, mi.display_priority,
               e.name as exchange_name
        FROM market_indices mi
        JOIN exchanges e ON mi.exchange_id = e.id
        WHERE mi.is_active = TRUE
        ORDER BY mi.market_code, mi.display_priority
    """)).fetchall()

    log.info("\n=== MARKET INDICES MAP (%d indices) ===", len(result))
    for r in result:
        log.info("  %-8s %-8s %-35s yahoo=%-20s prio=%d", r[0], r[1], r[2], r[3], r[4])

    session.close()
    log.info("Done. Total indices: %d", inserted)


if __name__ == "__main__":
    main()
