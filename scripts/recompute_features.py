#!/usr/bin/env python3
"""
Recompute feature_row entries for GOOGL, AMZN, NVDA from clean bar_1d data.
Run: ssh server_7 'docker exec -i <feature-builder-container> python3 -' < recompute_features.py
"""
import os, sys, math, logging
import pandas as pd
import numpy as np
import ta
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import execute_values

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── constants (inlined from /shared/feature_columns.py) ──────────────────────
TECHNICAL_COLS = ["ret_1d","ret_2d","ret_5d","ret_10d","ret_21d","rsi","macd","atr","stoch","ultosc"]
SHARADAR_COLS  = ["pe","pb","ps","evebitda","marketcap_log","roe","roa","debt_equity","revenue_growth","fcf_yield"]
ALL_FEATURE_COLS = TECHNICAL_COLS + SHARADAR_COLS

SYMBOLS    = ["GOOGL", "AMZN", "NVDA"]
START_DATE = "2015-01-01"
END_DATE   = "2025-05-26"

pool = ThreadedConnectionPool(1, 3, os.environ["DATABASE_URL"])


def fetch_bars(conn, symbol):
    return pd.read_sql(
        "SELECT time, symbol, open::float, high::float, low::float, close::float, volume::bigint "
        "FROM bar_1d WHERE symbol = %s AND time BETWEEN %s AND %s ORDER BY time",
        conn, params=(symbol, START_DATE, END_DATE),
    )


def fetch_sharadar_daily(conn, symbol, start, end):
    df = pd.read_sql(
        "SELECT date, pe::float, pb::float, ps::float, evebitda::float, marketcap::float "
        "FROM sharadar_daily WHERE ticker = %s AND date BETWEEN %s AND %s ORDER BY date",
        conn, params=(symbol, start, end),
    )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def fetch_fundamentals(conn, symbol, end):
    df = pd.read_sql(
        "SELECT calendardate, roe::float, roa::float, debt::float, equity::float, "
        "revenue::float, fcf::float, marketcap::float "
        "FROM sharadar_sf1 WHERE ticker = %s AND dimension = 'ARQ' AND calendardate <= %s "
        "ORDER BY calendardate",
        conn, params=(symbol, end),
    )
    if not df.empty:
        df["calendardate"] = pd.to_datetime(df["calendardate"])
        df["debt_equity"]    = np.where(df["equity"].notna() & (df["equity"] != 0), df["debt"] / df["equity"], np.nan)
        df["revenue_growth"] = df["revenue"].pct_change(4)
        df["fcf_yield"]      = np.where(df["marketcap"].notna() & (df["marketcap"] != 0), df["fcf"] / df["marketcap"], np.nan)
    return df


def merge_sharadar(bars_df, conn, symbol):
    bars_df = bars_df.copy()
    bars_df["time"] = pd.to_datetime(bars_df["time"]).dt.tz_localize("UTC") if bars_df["time"].dt.tz is None else bars_df["time"].dt.tz_convert("UTC")
    start, end = bars_df["time"].min().strftime("%Y-%m-%d"), bars_df["time"].max().strftime("%Y-%m-%d")

    daily = fetch_sharadar_daily(conn, symbol, start, end)
    if not daily.empty:
        daily = daily.rename(columns={"date": "time"})
        daily["time"] = pd.to_datetime(daily["time"]).dt.tz_localize("UTC")
        daily["marketcap_log"] = daily["marketcap"].apply(lambda x: math.log(x) if pd.notna(x) and x > 0 else np.nan)
        bars_df = bars_df.merge(daily[["time","pe","pb","ps","evebitda","marketcap_log"]], on="time", how="left")
    else:
        for c in ["pe","pb","ps","evebitda","marketcap_log"]: bars_df[c] = np.nan

    fund = fetch_fundamentals(conn, symbol, end)
    if not fund.empty:
        fund = fund.rename(columns={"calendardate": "time"})
        fund["time"] = pd.to_datetime(fund["time"]).dt.tz_localize("UTC")
        bars_df = pd.merge_asof(bars_df.sort_values("time"), fund[["time","roe","roa","debt_equity","revenue_growth","fcf_yield"]].sort_values("time"), on="time", direction="backward")
    else:
        for c in ["roe","roa","debt_equity","revenue_growth","fcf_yield"]: bars_df[c] = np.nan

    return bars_df


def compute_features(df):
    df = df.copy().sort_values("time")
    for n in [1,2,5,10,21]: df[f"ret_{n}d"] = df["close"].pct_change(n)
    df["rsi"]   = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
    df["macd"]  = ta.trend.MACD(df["close"]).macd_signal()
    df["atr"]   = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=14).average_true_range()
    stoch       = ta.momentum.StochasticOscillator(df["high"], df["low"], df["close"], window=14)
    df["stoch"] = stoch.stoch_signal() - stoch.stoch()
    df["ultosc"]= ta.momentum.UltimateOscillator(df["high"], df["low"], df["close"]).ultimate_oscillator()
    for c in ["pe","pb","ps","evebitda"]:
        if c in df.columns: df[c] = df[c].clip(-1000, 1000)
    return df.replace([np.inf, -np.inf], np.nan).dropna(subset=TECHNICAL_COLS)


def upsert(rows, conn):
    cols = ["time","symbol"] + ALL_FEATURE_COLS
    present = [c for c in cols if c in rows[0]]
    sql = (
        f"INSERT INTO feature_row ({','.join(present)}) VALUES %s "
        f"ON CONFLICT (time, symbol) DO UPDATE SET "
        + ", ".join(f"{c}=EXCLUDED.{c}" for c in present if c not in ("time","symbol"))
    )
    with conn.cursor() as cur:
        execute_values(cur, sql, [[r.get(c) for c in present] for r in rows], page_size=500)
    conn.commit()


for symbol in SYMBOLS:
    log.info("Processing %s ...", symbol)
    conn = pool.getconn()
    try:
        df = fetch_bars(conn, symbol)
        if df.empty:
            log.warning("%s: no bars, skipping", symbol)
            continue
        df = merge_sharadar(df, conn, symbol)
        conn.commit()
    finally:
        pool.putconn(conn)

    feat_df = compute_features(df)
    present = [c for c in ["time"] + ALL_FEATURE_COLS if c in feat_df.columns]
    rows = feat_df[present].assign(symbol=symbol).to_dict("records")

    conn = pool.getconn()
    try:
        upsert(rows, conn)
    finally:
        pool.putconn(conn)

    log.info("%s: upserted %d rows", symbol, len(rows))

log.info("Done.")
