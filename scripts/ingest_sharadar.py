#!/usr/bin/env python3
"""
Ingest SHARADAR CSV data into the alpaca-rl-suite TimescaleDB.

Uses pandas chunked CSV reads + psycopg2 execute_values per chunk.
Each chunk is committed individually so progress is never lost.
Idempotent: safe to re-run (upserts via ON CONFLICT).
Resumable: use --resume to skip tables that appear already loaded.

Usage:
    python scripts/ingest_sharadar.py                          # all tables
    python scripts/ingest_sharadar.py --tables sep sfp daily   # selective
    python scripts/ingest_sharadar.py --resume                 # skip done tables
    python scripts/ingest_sharadar.py --dry-run                # preview only

Requires: psycopg2-binary, pandas
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("ingest_sharadar")

DEFAULT_DATA_DIR = "/home/noslen/alpaca-trading/data/SHARADAR"
DEFAULT_DB_URL = os.getenv(
    "DATABASE_URL", "postgresql://rl_user:rl_pass@localhost:5432/alpaca_rl"
)
CHUNK = 10_000  # rows per chunk — small to keep memory and transaction size low

# SF1 columns we store as typed columns (rest go into JSONB extras)
SF1_TYPED_COLS = {
    "ticker", "dimension", "calendardate", "datekey", "reportperiod",
    "fiscalperiod", "lastupdated", "revenue", "netinc", "netinccmn",
    "gp", "ebit", "ebitda", "eps", "epsdil", "debt", "equity", "assets",
    "cashneq", "marketcap", "ev", "pe", "pb", "ps", "roe", "roa", "roic",
    "divyield", "fcf",
}


# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────
def get_conn(db_url: str):
    conn = psycopg2.connect(db_url)
    conn.set_session(autocommit=False)
    return conn


def run_migration(conn, migration_path: Path):
    """Run the SHARADAR migration SQL if tables don't exist yet."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'sharadar_tickers'
            )
        """)
        exists = cur.fetchone()[0]
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.columns
                WHERE table_name = 'bar_1d' AND column_name = 'source'
            )
        """)
        has_source = cur.fetchone()[0]
        if exists and has_source:
            log.info("Migration 002_sharadar already applied, skipping")
            return
    old = conn.autocommit
    conn.autocommit = True
    with conn.cursor() as cur:
        log.info("Running migration: %s", migration_path)
        cur.execute(migration_path.read_text())
    conn.autocommit = old
    log.info("Migration complete")


def v(val):
    """Convert pandas value to Python-native, None for NaN."""
    if pd.isna(val):
        return None
    return val


def fmt_count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def elapsed(t0: float) -> str:
    dt = time.time() - t0
    if dt < 60:
        return f"{dt:.1f}s"
    return f"{dt / 60:.1f}min"


def upsert_chunk(conn, sql, rows, table_label="", total=0, t0=0):
    """Execute upsert and commit. Returns new total."""
    with conn.cursor() as cur:
        execute_values(cur, sql, rows, page_size=2000)
    conn.commit()
    total += len(rows)
    log.info("  %s  %s rows  (%s)", table_label, fmt_count(total), elapsed(t0))
    sys.stdout.flush()
    time.sleep(0.1)  # throttle to reduce DB pressure
    return total


# ─────────────────────────────────────────
# SEP / SFP → bar_1d
# ─────────────────────────────────────────
PRICES_SQL = """
    INSERT INTO bar_1d (time, symbol, open, high, low, close, volume,
                        closeadj, closeunadj, source)
    VALUES %s
    ON CONFLICT (time, symbol) DO UPDATE SET
        open = EXCLUDED.open, high = EXCLUDED.high,
        low = EXCLUDED.low, close = EXCLUDED.close,
        volume = EXCLUDED.volume, closeadj = EXCLUDED.closeadj,
        closeunadj = EXCLUDED.closeunadj, source = EXCLUDED.source
"""


def ingest_prices(conn, csv_path: Path, source_name: str, dry_run=False):
    log.info("Loading %s → bar_1d (source=%s)", csv_path.name, source_name)
    t0 = time.time()
    total = 0

    for chunk in pd.read_csv(csv_path, chunksize=CHUNK, low_memory=False):
        chunk.columns = chunk.columns.str.strip().str.lower()
        rows = []
        for t in chunk.itertuples(index=False):
            adj = v(t.closeadj)
            rows.append((
                t.date, t.ticker, v(t.open), v(t.high), v(t.low),
                adj if adj is not None else v(t.close),
                int(t.volume) if pd.notna(t.volume) else 0,
                adj, v(t.closeunadj), source_name,
            ))
        if dry_run:
            total += len(rows)
            continue
        total = upsert_chunk(conn, PRICES_SQL, rows, csv_path.stem, total, t0)

    log.info("✓ %s: %s total in %s", csv_path.name, fmt_count(total), elapsed(t0))
    return total


# ─────────────────────────────────────────
# SHARADAR_DAILY → sharadar_daily
# ─────────────────────────────────────────
DAILY_SQL = """
    INSERT INTO sharadar_daily (ticker, date, lastupdated, ev, evebit,
                                evebitda, marketcap, pb, pe, ps)
    VALUES %s
    ON CONFLICT (date, ticker) DO UPDATE SET
        lastupdated = EXCLUDED.lastupdated,
        ev = EXCLUDED.ev, evebit = EXCLUDED.evebit,
        evebitda = EXCLUDED.evebitda, marketcap = EXCLUDED.marketcap,
        pb = EXCLUDED.pb, pe = EXCLUDED.pe, ps = EXCLUDED.ps
"""


def ingest_daily(conn, csv_path: Path, dry_run=False):
    log.info("Loading %s → sharadar_daily", csv_path.name)
    t0 = time.time()
    total = 0

    for chunk in pd.read_csv(csv_path, chunksize=CHUNK, low_memory=False):
        chunk.columns = chunk.columns.str.strip().str.lower()
        rows = [
            (t.ticker, t.date, v(t.lastupdated), v(t.ev), v(t.evebit),
             v(t.evebitda), v(t.marketcap), v(t.pb), v(t.pe), v(t.ps))
            for t in chunk.itertuples(index=False)
        ]
        if dry_run:
            total += len(rows)
            continue
        total = upsert_chunk(conn, DAILY_SQL, rows, "daily", total, t0)

    log.info("✓ %s: %s total in %s", csv_path.name, fmt_count(total), elapsed(t0))
    return total


# ─────────────────────────────────────────
# SHARADAR_SF1 → sharadar_sf1
# ─────────────────────────────────────────
SF1_SQL = """
    INSERT INTO sharadar_sf1
        (ticker, dimension, calendardate, datekey, reportperiod,
         fiscalperiod, lastupdated,
         revenue, netinc, netinccmn, gp, ebit, ebitda,
         eps, epsdil, debt, equity, assets, cashneq,
         marketcap, ev, pe, pb, ps, roe, roa, roic,
         divyield, fcf, extras)
    VALUES %s
    ON CONFLICT (calendardate, ticker, dimension) DO UPDATE SET
        datekey = EXCLUDED.datekey, reportperiod = EXCLUDED.reportperiod,
        fiscalperiod = EXCLUDED.fiscalperiod, lastupdated = EXCLUDED.lastupdated,
        revenue = EXCLUDED.revenue, netinc = EXCLUDED.netinc,
        netinccmn = EXCLUDED.netinccmn, gp = EXCLUDED.gp,
        ebit = EXCLUDED.ebit, ebitda = EXCLUDED.ebitda,
        eps = EXCLUDED.eps, epsdil = EXCLUDED.epsdil,
        debt = EXCLUDED.debt, equity = EXCLUDED.equity,
        assets = EXCLUDED.assets, cashneq = EXCLUDED.cashneq,
        marketcap = EXCLUDED.marketcap, ev = EXCLUDED.ev,
        pe = EXCLUDED.pe, pb = EXCLUDED.pb, ps = EXCLUDED.ps,
        roe = EXCLUDED.roe, roa = EXCLUDED.roa, roic = EXCLUDED.roic,
        divyield = EXCLUDED.divyield, fcf = EXCLUDED.fcf,
        extras = EXCLUDED.extras
"""


def ingest_sf1(conn, csv_path: Path, dry_run=False):
    log.info("Loading %s → sharadar_sf1", csv_path.name)
    t0 = time.time()
    total = 0

    # Read header to find extras columns
    header = pd.read_csv(csv_path, nrows=0).columns.str.strip().str.lower().tolist()
    extras_cols = [c for c in header if c not in SF1_TYPED_COLS]

    for chunk in pd.read_csv(csv_path, chunksize=CHUNK, low_memory=False):
        chunk.columns = chunk.columns.str.strip().str.lower()
        # Deduplicate within chunk
        chunk = chunk.drop_duplicates(subset=["calendardate", "ticker", "dimension"], keep="last")
        rows = []
        for t in chunk.itertuples(index=False):
            extras = {}
            for c in extras_cols:
                val = getattr(t, c, None)
                if pd.notna(val):
                    extras[c] = val
            rows.append((
                t.ticker, t.dimension, t.calendardate,
                v(t.datekey), v(t.reportperiod), v(t.fiscalperiod), v(t.lastupdated),
                v(t.revenue), v(t.netinc), v(t.netinccmn), v(t.gp),
                v(t.ebit), v(t.ebitda), v(t.eps), v(t.epsdil),
                v(t.debt), v(t.equity), v(t.assets), v(t.cashneq),
                v(t.marketcap), v(t.ev), v(t.pe), v(t.pb), v(t.ps),
                v(t.roe), v(t.roa), v(t.roic), v(t.divyield), v(t.fcf),
                json.dumps(extras) if extras else None,
            ))
        if dry_run:
            total += len(rows)
            continue
        total = upsert_chunk(conn, SF1_SQL, rows, "sf1", total, t0)

    log.info("✓ %s: %s total in %s", csv_path.name, fmt_count(total), elapsed(t0))
    return total


# ─────────────────────────────────────────
# SHARADAR_TICKERS → sharadar_tickers
# ─────────────────────────────────────────
TICKERS_SQL = """
    INSERT INTO sharadar_tickers
        ("table", permaticker, ticker, name, exchange, isdelisted,
         category, cusips, siccode, sicsector, sicindustry,
         famasector, famaindustry, sector, industry,
         scalemarketcap, scalerevenue, relatedtickers, currency,
         location, lastupdated, firstadded, firstpricedate,
         lastpricedate, firstquarter, lastquarter,
         secfilings, companysite)
    VALUES %s
    ON CONFLICT (ticker) DO UPDATE SET
        "table" = EXCLUDED."table", permaticker = EXCLUDED.permaticker,
        name = EXCLUDED.name, exchange = EXCLUDED.exchange,
        isdelisted = EXCLUDED.isdelisted, sector = EXCLUDED.sector,
        industry = EXCLUDED.industry, lastupdated = EXCLUDED.lastupdated
"""


def ingest_tickers(conn, csv_path: Path, dry_run=False):
    log.info("Loading %s → sharadar_tickers", csv_path.name)
    t0 = time.time()

    df = pd.read_csv(csv_path, low_memory=False)
    df.columns = df.columns.str.strip().str.lower()
    df = df.drop_duplicates(subset=["ticker"], keep="last")
    df = df[df["ticker"].notna()]

    rows = []
    for t in df.itertuples(index=False):
        rows.append((
            v(getattr(t, "table", None)), v(t.permaticker), t.ticker,
            v(t.name), v(t.exchange), v(t.isdelisted), v(t.category),
            v(t.cusips), v(t.siccode), v(t.sicsector), v(t.sicindustry),
            v(t.famasector), v(t.famaindustry), v(t.sector), v(t.industry),
            v(t.scalemarketcap), v(t.scalerevenue), v(t.relatedtickers),
            v(t.currency), v(t.location), v(t.lastupdated), v(t.firstadded),
            v(t.firstpricedate), v(t.lastpricedate), v(t.firstquarter),
            v(t.lastquarter), v(t.secfilings), v(t.companysite),
        ))

    if dry_run:
        log.info("  [dry-run] %s rows", len(rows))
        return len(rows)

    total = upsert_chunk(conn, TICKERS_SQL, rows, "tickers", 0, t0)
    log.info("✓ %s: %s total in %s", csv_path.name, fmt_count(total), elapsed(t0))
    return total


# ─────────────────────────────────────────
# SHARADAR_ACTIONS → sharadar_actions
# ─────────────────────────────────────────
ACTIONS_SQL = """
    INSERT INTO sharadar_actions (date, action, ticker, name, value,
                                  contraticker, contraname)
    VALUES %s
    ON CONFLICT (date, ticker, action) DO UPDATE SET
        name = EXCLUDED.name, value = EXCLUDED.value,
        contraticker = EXCLUDED.contraticker, contraname = EXCLUDED.contraname
"""


def ingest_actions(conn, csv_path: Path, dry_run=False):
    log.info("Loading %s → sharadar_actions", csv_path.name)
    t0 = time.time()
    total = 0

    for chunk in pd.read_csv(csv_path, chunksize=CHUNK, low_memory=False):
        chunk.columns = chunk.columns.str.strip().str.lower()
        chunk = chunk.drop_duplicates(subset=["date", "ticker", "action"], keep="last")
        chunk = chunk.dropna(subset=["date", "ticker", "action"])
        rows = [
            (t.date, t.action, t.ticker, v(t.name), v(t.value),
             v(t.contraticker), v(t.contraname))
            for t in chunk.itertuples(index=False)
        ]
        if dry_run:
            total += len(rows)
            continue
        total = upsert_chunk(conn, ACTIONS_SQL, rows, "actions", total, t0)

    log.info("✓ %s: %s total in %s", csv_path.name, fmt_count(total), elapsed(t0))
    return total


# ─────────────────────────────────────────
# SHARADAR_SP500 → sharadar_sp500
# ─────────────────────────────────────────
SP500_SQL = """
    INSERT INTO sharadar_sp500 (date, action, ticker, name,
                                contraticker, contraname, note)
    VALUES %s
    ON CONFLICT (date, ticker, action) DO UPDATE SET
        name = EXCLUDED.name, contraticker = EXCLUDED.contraticker,
        contraname = EXCLUDED.contraname, note = EXCLUDED.note
"""


def ingest_sp500(conn, csv_path: Path, dry_run=False):
    log.info("Loading %s → sharadar_sp500", csv_path.name)
    t0 = time.time()

    df = pd.read_csv(csv_path, low_memory=False)
    df.columns = df.columns.str.strip().str.lower()
    df = df.drop_duplicates(subset=["date", "ticker", "action"], keep="last")
    df = df.dropna(subset=["date", "ticker", "action"])

    rows = [
        (t.date, t.action, t.ticker, v(t.name),
         v(t.contraticker), v(t.contraname), v(t.note))
        for t in df.itertuples(index=False)
    ]

    if dry_run:
        log.info("  [dry-run] %s rows", len(rows))
        return len(rows)

    total = upsert_chunk(conn, SP500_SQL, rows, "sp500", 0, t0)
    log.info("✓ %s: %s total in %s", csv_path.name, fmt_count(total), elapsed(t0))
    return total


# ─────────────────────────────────────────
# Main
# ─────────────────────────────────────────
ALL_TABLES = ["sep", "sfp", "sf1", "daily", "tickers", "actions", "sp500"]

CSV_MAP = {
    "sep":     "SHARADAR_SEP.csv",
    "sfp":     "SHARADAR_SFP.csv",
    "sf1":     "SHARADAR_SF1.csv",
    "daily":   "SHARADAR_DAILY.csv",
    "tickers": "SHARADAR_TICKERS.csv",
    "actions": "SHARADAR_ACTIONS.csv",
    "sp500":   "SHARADAR_SP500.csv",
}

EXPECTED_COUNTS = {
    "sep": ("bar_1d", "sharadar_sep", 17_000_000),
    "sfp": ("bar_1d", "sharadar_sfp", 8_000_000),
    "daily": ("sharadar_daily", None, 14_000_000),
    "sf1": ("sharadar_sf1", None, 1_000_000),
    "tickers": ("sharadar_tickers", None, 10_000),
    "actions": ("sharadar_actions", None, 200_000),
    "sp500": ("sharadar_sp500", None, 5_000),
}


def check_resume(conn, table_key: str) -> bool:
    tbl, source_filter, expected = EXPECTED_COUNTS[table_key]
    try:
        with conn.cursor() as cur:
            if source_filter:
                cur.execute(f"SELECT count(*) FROM {tbl} WHERE source = %s", (source_filter,))
            else:
                cur.execute(f"SELECT count(*) FROM {tbl}")
            actual = cur.fetchone()[0]
        if actual > expected * 0.8:
            log.info("  SKIP %s: already has %s rows (expected ~%s)",
                     table_key, fmt_count(actual), fmt_count(expected))
            return True
        elif actual > 0:
            log.info("  PARTIAL %s: has %s rows, will reload", table_key, fmt_count(actual))
        return False
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description="Ingest SHARADAR data into alpaca-rl-suite DB")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    parser.add_argument("--db-url", default=DEFAULT_DB_URL)
    parser.add_argument("--tables", nargs="+", choices=ALL_TABLES, default=ALL_TABLES)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-migration", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.is_dir():
        log.error("Data directory not found: %s", data_dir)
        sys.exit(1)

    for table in args.tables:
        csv_file = data_dir / CSV_MAP[table]
        if not csv_file.exists():
            log.error("CSV not found: %s", csv_file)
            sys.exit(1)

    log.info("Connecting to database...")
    conn = get_conn(args.db_url)

    if not args.skip_migration and not args.dry_run:
        migration_path = Path(__file__).parent.parent / "infra" / "migrations" / "002_sharadar.sql"
        if migration_path.exists():
            run_migration(conn, migration_path)
        else:
            log.warning("Migration file not found at %s, skipping", migration_path)

    results = {}
    t_global = time.time()

    ordered = [t for t in ["tickers", "sp500", "actions", "sf1", "sep", "sfp", "daily"]
               if t in args.tables]

    for table in ordered:
        csv_path = data_dir / CSV_MAP[table]

        if args.resume and not args.dry_run:
            if check_resume(conn, table):
                results[table] = {"rows": 0, "status": "skipped"}
                continue

        try:
            if table == "sep":
                n = ingest_prices(conn, csv_path, "sharadar_sep", args.dry_run)
            elif table == "sfp":
                n = ingest_prices(conn, csv_path, "sharadar_sfp", args.dry_run)
            elif table == "daily":
                n = ingest_daily(conn, csv_path, args.dry_run)
            elif table == "sf1":
                n = ingest_sf1(conn, csv_path, args.dry_run)
            elif table == "tickers":
                n = ingest_tickers(conn, csv_path, args.dry_run)
            elif table == "actions":
                n = ingest_actions(conn, csv_path, args.dry_run)
            elif table == "sp500":
                n = ingest_sp500(conn, csv_path, args.dry_run)
            results[table] = {"rows": n, "status": "ok"}
        except Exception as e:
            log.error("Failed to ingest %s: %s", table, e, exc_info=True)
            results[table] = {"rows": 0, "status": "error", "error": str(e)}
            conn.rollback()

    conn.close()

    log.info("=" * 60)
    log.info("INGESTION SUMMARY (%s)", elapsed(t_global))
    log.info("=" * 60)
    for table, info in results.items():
        log.info("  %-10s %10s rows  [%s]", table, fmt_count(info["rows"]), info["status"].upper())
    log.info("=" * 60)
    sys.stdout.flush()

    if any(r["status"] == "error" for r in results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
