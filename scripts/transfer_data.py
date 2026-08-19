#!/usr/bin/env python3
"""Transfer raw data from market DB to quant DB with column mapping."""

import psycopg2
import sys
from datetime import datetime

MARKET_DB = "postgresql://petrick:market_dev@localhost:5432/market"
QUANT_DB = "postgresql://petrick:market_dev@localhost:5432/quant"


def transfer_table(src_conn, dst_conn, src_table, dst_table, columns_map, where=""):
    """Generic transfer with column mapping.
    
    columns_map: dict of {dst_col: (src_col, cast_sql or None)}
    """
    src_cols = [v[0] for v in columns_map.values()]
    dst_cols = list(columns_map.keys())
    
    select_cols = []
    for dst_col, (src_col, cast) in columns_map.items():
        if cast:
            select_cols.append(f"{cast} AS {dst_col}")
        else:
            select_cols.append(src_col)
    
    select_sql = f"SELECT {', '.join(select_cols)} FROM {src_table}"
    if where:
        select_sql += f" WHERE {where}"
    
    cur_src = src_conn.cursor()
    cur_src.execute(select_sql)
    rows = cur_src.fetchall()
    
    if not rows:
        print(f"  {src_table} → {dst_table}: 0 rows")
        return 0
    
    insert_cols = ', '.join(dst_cols)
    placeholders = ', '.join(['%s'] * len(dst_cols))
    insert_sql = f"INSERT INTO {dst_table} ({insert_cols}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
    
    cur_dst = dst_conn.cursor()
    cur_dst.executemany(insert_sql, rows)
    dst_conn.commit()
    
    print(f"  {src_table} → {dst_table}: {len(rows)} rows")
    cur_src.close()
    cur_dst.close()
    return len(rows)


def main():
    print("=== Transfer raw data: market → quant ===\n")
    
    src = psycopg2.connect(MARKET_DB)
    dst = psycopg2.connect(QUANT_DB)
    
    # 1. Exchanges
    print("[1/10] Exchanges...")
    transfer_table(src, dst, "exchanges", "exchanges", {
        "mic": ("mic_code", None),
        "name": ("name", None),
        "country": ("country_code", None),
        "timezone": ("timezone", None),
        "currency": ("currency", None),
        "is_active": ("is_active", None),
    })
    
    # 2. Sector master
    print("[2/10] Sector master...")
    transfer_table(src, dst, "sector_master", "sector_master", {
        "code": ("kode", None),
        "name": ("nama", None),
    })
    
    # 3. Instruments
    print("[3/10] Instruments...")
    transfer_table(src, dst, "instruments", "instruments", {
        "ticker": ("ticker", None),
        "sector_id": ("sector", "NULL::integer"),  # will need mapping
        "asset_class": ("asset_class", None),
        "currency": ("currency", None),
        "lot_size": ("lot_size", None),
        "is_active": ("is_active", None),
        "listed_date": ("listed_at", None),
        "delisted_date": ("delisting_date", None),
        "company_name": ("name", None),
    })
    
    # Link instruments to exchanges via exchange_mic
    print("  Linking instruments → exchanges...")
    cur_dst = dst.cursor()
    # First add Unknown sector if not exists
    cur_dst.execute("INSERT INTO sector_master (code, name) VALUES ('MISC', 'Unknown') ON CONFLICT DO NOTHING")
    # Link to XIDX exchange for all IDX instruments
    cur_dst.execute("""
        UPDATE instruments i SET exchange_id = e.id 
        FROM exchanges e 
        WHERE i.exchange_id IS NULL AND e.mic = 'XIDX'
    """)
    # Link sectors by name — try matching sector names
    cur_dst.execute("""
        UPDATE instruments i SET sector_id = s.id 
        FROM sector_master s 
        WHERE i.sector_id IS NULL
    """)
    # Set default sector for those without
    cur_dst.execute("""
        UPDATE instruments SET sector_id = (SELECT id FROM sector_master WHERE name = 'Unknown' LIMIT 1)
        WHERE sector_id IS NULL
    """)
    dst.commit()
    cur_dst.close()
    
    # 4. Stock prices (market.stock_prices: timestamp → quant.stock_prices: date)
    print("[4/10] Stock prices...")
    transfer_table(src, dst, "stock_prices", "stock_prices", {
        "ticker": ("ticker", None),
        "date": ("timestamp", "timestamp::date"),
        "open": ("open", None),
        "high": ("high", None),
        "low": ("low", None),
        "close": ("close", None),
        "volume": ("volume", None),
        "adj_close": ("adjusted_close", None),
    })
    
    # 5. Foreign flow
    print("[5/10] Foreign flow...")
    transfer_table(src, dst, "foreign_flow", "foreign_flow", {
        "ticker": ("ticker", None),
        "date": ("date", None),
        "foreign_buy": ("foreign_buy", None),
        "foreign_sell": ("foreign_sell", None),
        "foreign_net": ("foreign_net", None),
        "domestic_buy": ("domestic_buy", None),
        "domestic_sell": ("domestic_sell", None),
        "domestic_net": ("domestic_net", None),
    })
    
    # 6. Macro data
    print("[6/10] Macro data...")
    transfer_table(src, dst, "macro_data", "macro_data", {
        "series_name": ("series_name", None),
        "date": ("date", None),
        "value": ("value", None),
        "unit": ("unit", None),
        "source": ("source", None),
    })
    
    # 7. Fundamental data
    print("[7/10] Fundamental data...")
    # Map columns from market schema to quant schema
    fund_map = {
        "ticker": ("ticker", None),
        "date": ("date", None),
        "period": ("quarter", None),
        "revenue": ("revenue", None),
        "net_income": ("net_income", None),
        "total_assets": ("total_assets", None),
        "total_debt": ("total_debt", None),
        "eps": ("eps", None),
        "book_value_per_share": ("book_value_per_share", None),
        "roe": ("return_on_equity", None),
        "roa": ("return_on_assets", None),
        "debt_ratio": ("debt_to_equity", None),
        "current_ratio": ("current_ratio", None),
        "pe_ratio": ("pe", None),
        "pb_ratio": ("pb", None),
        "dividend_yield": ("dividend_yield", None),
        "market_cap": ("market_cap", None),
        "operating_cash_flow": ("cash_flow", None),
    }
    transfer_table(src, dst, "fundamental_data", "fundamental_data", fund_map)
    
    # 8. News sentiment
    print("[8/10] News sentiment...")
    cur_src = src.cursor()
    cur_src.execute("SELECT column_name FROM information_schema.columns WHERE table_name='news_sentiment' ORDER BY ordinal_position;")
    src_cols_news = [r[0] for r in cur_src.fetchall()]
    cur_src.close()
    
    news_map = {}
    col_mapping = {
        "ticker": "ticker",
        "date": "date",
        "headline": "headline",
        "sentiment_score": "sentiment_score",
        "sentiment_label": "sentiment_label",
        "source": "source",
        "url": "url",
    }
    for dst_col, src_col in col_mapping.items():
        if src_col in src_cols_news:
            news_map[dst_col] = (src_col, None)
    
    transfer_table(src, dst, "news_sentiment", "news_sentiment", news_map)
    
    # 9. Exchange holidays
    print("[9/10] Exchange holidays...")
    transfer_table(src, dst, "exchange_holidays", "exchange_holidays", {
        "exchange_id": ("mic_code", "NULL::integer"),
        "holiday_date": ("holiday_date", None),
        "name": ("holiday_name", None),
        "type": ("is_half_day", "CASE WHEN is_half_day THEN 'half_day' ELSE 'full_day' END"),
    })
    # Link to exchanges by mic_code
    cur_dst = dst.cursor()
    cur_dst.execute("""
        UPDATE exchange_holidays eh SET exchange_id = e.id 
        FROM exchanges e 
        WHERE eh.exchange_id IS NULL
    """)
    dst.commit()
    cur_dst.close()
    
    # 10. Policy events + External events
    print("[10/10] Policy & External events...")
    transfer_table(src, dst, "policy_events", "policy_events", {
        "date": ("date", None),
        "title": ("title", None),
        "category": ("category", None),
        "impact": ("impact", None),
        "direction": ("direction", None),
        "description": ("description", None),
        "source": ("source", None),
    })
    
    transfer_table(src, dst, "external_events", "external_events", {
        "date": ("date", None),
        "title": ("title", None),
        "category": ("category", None),
        "impact_market": ("impact_market", None),
        "description": ("description", None),
        "source": ("source", None),
    })
    
    # Corporate calendar
    print("[bonus] Corporate calendar...")
    transfer_table(src, dst, "corporate_calendar", "corporate_calendar", {
        "ticker": ("ticker", None),
        "event_date": ("event_date", None),
        "event_type": ("event_type", None),
        "title": ("title", None),
        "description": ("description", None),
        "location": ("location", None),
    })
    
    # Summary
    print("\n=== Transfer complete ===")
    cur_dst = dst.cursor()
    for table in ["exchanges", "sector_master", "instruments", "stock_prices", 
                  "foreign_flow", "macro_data", "fundamental_data", "news_sentiment",
                  "exchange_holidays", "policy_events", "external_events", "corporate_calendar"]:
        cur_dst.execute(f"SELECT COUNT(*) FROM {table}")
        count = cur_dst.fetchone()[0]
        print(f"  {table}: {count:,} rows")
    cur_dst.close()
    
    src.close()
    dst.close()


if __name__ == "__main__":
    main()
