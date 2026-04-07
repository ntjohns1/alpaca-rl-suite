import os
import sys
import math
import logging
from contextlib import asynccontextmanager
from observability import setup_observability

import pandas as pd
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import psycopg2
from psycopg2.extras import execute_values
import ta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))
from feature_columns import TECHNICAL_COLS, SHARADAR_COLS, ALL_FEATURE_COLS

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
FEATURE_BUILDER_PORT = int(os.getenv("FEATURE_BUILDER_PORT", "8002"))


def get_conn():
    return psycopg2.connect(DATABASE_URL)


# ─────────────────────────────────────────
# SHARADAR data fetchers
# ─────────────────────────────────────────
def fetch_sharadar_daily(conn, symbol: str, start_date, end_date) -> pd.DataFrame:
    """Fetch daily valuation metrics from sharadar_daily for a symbol."""
    df = pd.read_sql(
        """
        SELECT date, ticker,
               pe::float, pb::float, ps::float,
               evebitda::float, marketcap::float
        FROM sharadar_daily
        WHERE ticker = %s AND date BETWEEN %s AND %s
        ORDER BY date
        """,
        conn,
        params=(symbol, start_date, end_date),
    )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def fetch_fundamentals(conn, symbol: str, end_date) -> pd.DataFrame:
    """Fetch latest quarterly fundamentals (ARQ dimension) from sharadar_sf1.
    Returns one row per calendardate with key ratios and computed metrics."""
    df = pd.read_sql(
        """
        SELECT calendardate, ticker,
               roe::float, roa::float,
               debt::float, equity::float,
               revenue::float, fcf::float, marketcap::float
        FROM sharadar_sf1
        WHERE ticker = %s
          AND dimension = 'ARQ'
          AND calendardate <= %s
        ORDER BY calendardate
        """,
        conn,
        params=(symbol, end_date),
    )
    if df.empty:
        return df
    df["calendardate"] = pd.to_datetime(df["calendardate"])
    # Compute derived metrics
    df["debt_equity"] = np.where(
        (df["equity"].notna()) & (df["equity"] != 0),
        df["debt"] / df["equity"],
        np.nan,
    )
    df["revenue_growth"] = df["revenue"].pct_change(4)  # YoY (4 quarters)
    df["fcf_yield"] = np.where(
        (df["marketcap"].notna()) & (df["marketcap"] != 0),
        df["fcf"] / df["marketcap"],
        np.nan,
    )
    return df


def merge_sharadar_features(bars_df: pd.DataFrame, conn, symbol: str) -> pd.DataFrame:
    """LEFT JOIN SHARADAR daily + fundamentals onto the bars DataFrame."""
    if bars_df.empty:
        return bars_df

    start_date = bars_df["time"].min().strftime("%Y-%m-%d")
    end_date = bars_df["time"].max().strftime("%Y-%m-%d")

    # --- Daily valuation metrics ---
    daily = fetch_sharadar_daily(conn, symbol, start_date, end_date)
    if not daily.empty:
        daily = daily.rename(columns={"date": "time"})
        daily["time"] = pd.to_datetime(daily["time"]).dt.tz_localize("UTC")
        daily["marketcap_log"] = daily["marketcap"].apply(
            lambda x: math.log(x) if pd.notna(x) and x > 0 else np.nan
        )
        merge_cols = ["time", "pe", "pb", "ps", "evebitda", "marketcap_log"]
        bars_df = bars_df.merge(daily[merge_cols], on="time", how="left")
    else:
        for col in ["pe", "pb", "ps", "evebitda", "marketcap_log"]:
            bars_df[col] = np.nan

    # --- Quarterly fundamentals (forward-filled to daily) ---
    fund = fetch_fundamentals(conn, symbol, end_date)
    if not fund.empty:
        fund = fund.rename(columns={"calendardate": "time"})
        fund["time"] = pd.to_datetime(fund["time"]).dt.tz_localize("UTC")
        fund_cols = ["time", "roe", "roa", "debt_equity", "revenue_growth", "fcf_yield"]
        bars_df = pd.merge_asof(
            bars_df.sort_values("time"),
            fund[fund_cols].sort_values("time"),
            on="time",
            direction="backward",
        )
    else:
        for col in ["roe", "roa", "debt_equity", "revenue_growth", "fcf_yield"]:
            bars_df[col] = np.nan

    return bars_df


# ─────────────────────────────────────────
# Feature computation
# Mirrors trading_env.py: returns, rsi, macd, atr, stoch, ultosc
# + SHARADAR valuation & fundamental features
# ─────────────────────────────────────────
def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Input: DataFrame with columns [time, symbol, open, high, low, close, volume]
           + optional SHARADAR columns (pe, pb, ps, evebitda, marketcap_log, ...)
    Output: DataFrame with all RL state features appended
    """
    df = df.copy().sort_values("time")

    # Returns
    df["ret_1d"]  = df["close"].pct_change(1)
    df["ret_2d"]  = df["close"].pct_change(2)
    df["ret_5d"]  = df["close"].pct_change(5)
    df["ret_10d"] = df["close"].pct_change(10)
    df["ret_21d"] = df["close"].pct_change(21)

    # Technical indicators (using `ta` library — pure Python, no TA-Lib dependency)
    df["rsi"]    = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
    macd_obj     = ta.trend.MACD(df["close"])
    df["macd"]   = macd_obj.macd_signal()
    df["atr"]    = ta.volatility.AverageTrueRange(
        df["high"], df["low"], df["close"], window=14
    ).average_true_range()
    stoch_obj    = ta.momentum.StochasticOscillator(
        df["high"], df["low"], df["close"], window=14
    )
    df["stoch"]  = stoch_obj.stoch_signal() - stoch_obj.stoch()
    df["ultosc"] = ta.momentum.UltimateOscillator(
        df["high"], df["low"], df["close"]
    ).ultimate_oscillator()

    # Winsorize SHARADAR valuation ratios to cap extreme outliers
    for col in ["pe", "pb", "ps", "evebitda"]:
        if col in df.columns:
            df[col] = df[col].clip(lower=-1000, upper=1000)

    df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=TECHNICAL_COLS)
    return df


def build_state_vector(row: pd.Series) -> list[float]:
    """Build the 20-element state vector matching trading_env.py DataSource."""
    vec = []
    for c in ALL_FEATURE_COLS:
        v = row.get(c, 0.0)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            v = 0.0
        vec.append(float(v))
    return vec


# ─────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────
def fetch_bars(symbol: str, days: int = 60, conn=None) -> pd.DataFrame:
    close_conn = conn is None
    if conn is None:
        conn = get_conn()
    try:
        df = pd.read_sql(
            """
            SELECT time, symbol, open::float, high::float, low::float,
                   close::float, volume::bigint
            FROM bar_1d
            WHERE symbol = %s
            ORDER BY time DESC
            LIMIT %s
            """,
            conn,
            params=(symbol, days),
        )
    finally:
        if close_conn:
            conn.close()
    return df.sort_values("time").reset_index(drop=True)


def _safe_float(val):
    """Convert to float, returning None for NaN/inf."""
    if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
        return None
    return float(val)


def upsert_features(rows: list[dict]):
    if not rows:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO feature_row
                  (time, symbol, ret_1d, ret_2d, ret_5d, ret_10d, ret_21d,
                   rsi, macd, atr, stoch, ultosc,
                   pe, pb, ps, evebitda, marketcap_log,
                   roe, roa, debt_equity, revenue_growth, fcf_yield)
                VALUES %s
                ON CONFLICT (time, symbol) DO UPDATE SET
                  ret_1d=EXCLUDED.ret_1d, ret_2d=EXCLUDED.ret_2d,
                  ret_5d=EXCLUDED.ret_5d, ret_10d=EXCLUDED.ret_10d,
                  ret_21d=EXCLUDED.ret_21d, rsi=EXCLUDED.rsi,
                  macd=EXCLUDED.macd, atr=EXCLUDED.atr,
                  stoch=EXCLUDED.stoch, ultosc=EXCLUDED.ultosc,
                  pe=EXCLUDED.pe, pb=EXCLUDED.pb,
                  ps=EXCLUDED.ps, evebitda=EXCLUDED.evebitda,
                  marketcap_log=EXCLUDED.marketcap_log,
                  roe=EXCLUDED.roe, roa=EXCLUDED.roa,
                  debt_equity=EXCLUDED.debt_equity,
                  revenue_growth=EXCLUDED.revenue_growth,
                  fcf_yield=EXCLUDED.fcf_yield
                """,
                [
                    (
                        r["time"], r["symbol"],
                        r["ret_1d"], r["ret_2d"], r["ret_5d"], r["ret_10d"], r["ret_21d"],
                        r["rsi"], r["macd"], r["atr"], r["stoch"], r["ultosc"],
                        _safe_float(r.get("pe")), _safe_float(r.get("pb")),
                        _safe_float(r.get("ps")), _safe_float(r.get("evebitda")),
                        _safe_float(r.get("marketcap_log")),
                        _safe_float(r.get("roe")), _safe_float(r.get("roa")),
                        _safe_float(r.get("debt_equity")),
                        _safe_float(r.get("revenue_growth")),
                        _safe_float(r.get("fcf_yield")),
                    )
                    for r in rows
                ],
            )
        conn.commit()


# ─────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Feature Builder started")
    yield
    log.info("Feature Builder shutdown")


app = FastAPI(title="Feature Builder", lifespan=lifespan)
setup_observability(app, "feature-builder")


class BuildFeaturesRequest(BaseModel):
    symbols: list[str]
    days: int = 252


class ComputeFeaturesRequest(BaseModel):
    symbols: list[str]
    start_date: str
    end_date: str


@app.post("/features/build")
def build_features(req: BuildFeaturesRequest):
    results = {}
    for symbol in req.symbols:
        try:
            with get_conn() as conn:
                df = fetch_bars(symbol, req.days, conn=conn)
                if len(df) < 22:
                    results[symbol] = {"status": "insufficient_data", "rows": len(df)}
                    continue
                df = merge_sharadar_features(df, conn, symbol)
            feat_df = compute_features(df)
            out_cols = ["time"] + ALL_FEATURE_COLS
            present = [c for c in out_cols if c in feat_df.columns]
            rows = feat_df[present].assign(symbol=symbol).to_dict("records")
            upsert_features(rows)
            results[symbol] = {"status": "ok", "rows": len(rows)}
            log.info(f"Built {len(rows)} feature rows for {symbol}")
        except Exception as e:
            log.error(f"Feature build failed for {symbol}: {e}")
            results[symbol] = {"status": "error", "error": str(e)}
    return results


@app.post("/features/compute")
def compute_features_for_range(req: ComputeFeaturesRequest):
    """On-demand feature computation for a specific date range."""
    results = {}
    for symbol in req.symbols:
        try:
            with get_conn() as conn:
                df = pd.read_sql(
                    """
                    SELECT time, symbol, open::float, high::float, low::float,
                           close::float, volume::bigint
                    FROM bar_1d
                    WHERE symbol = %s
                      AND time BETWEEN %s AND %s
                    ORDER BY time
                    """,
                    conn,
                    params=(symbol, req.start_date, req.end_date),
                )
                if len(df) < 22:
                    results[symbol] = {"status": "insufficient_data", "rows": len(df)}
                    continue
                df = merge_sharadar_features(df, conn, symbol)
            feat_df = compute_features(df)
            out_cols = ["time"] + ALL_FEATURE_COLS
            present = [c for c in out_cols if c in feat_df.columns]
            rows = feat_df[present].assign(symbol=symbol).to_dict("records")
            upsert_features(rows)
            results[symbol] = {"status": "ok", "rows": len(rows)}
            log.info(f"Computed {len(rows)} feature rows for {symbol} [{req.start_date} → {req.end_date}]")
        except Exception as e:
            log.error(f"Feature compute failed for {symbol}: {e}")
            results[symbol] = {"status": "error", "error": str(e)}
    return results


@app.get("/features/availability")
def check_feature_availability(
    symbols: str,
    start_date: str,
    end_date: str,
):
    """Check how many feature rows exist for the given symbols and date range."""
    symbol_list = [s.strip() for s in symbols.split(",")]
    results = {}
    with get_conn() as conn:
        for symbol in symbol_list:
            row = pd.read_sql(
                """
                SELECT COUNT(*) as feature_count
                FROM feature_row
                WHERE symbol = %s AND time BETWEEN %s AND %s
                """,
                conn,
                params=(symbol, start_date, end_date),
            )
            bar_row = pd.read_sql(
                """
                SELECT COUNT(*) as bar_count
                FROM bar_1d
                WHERE symbol = %s AND time BETWEEN %s AND %s
                """,
                conn,
                params=(symbol, start_date, end_date),
            )
            results[symbol] = {
                "feature_rows": int(row.iloc[0]["feature_count"]),
                "bar_rows": int(bar_row.iloc[0]["bar_count"]),
            }
    return results


@app.get("/features/latest/{symbol}")
def get_latest_features(symbol: str):
    try:
        with get_conn() as conn:
            df = fetch_bars(symbol, 60, conn=conn)
            if len(df) < 22:
                raise HTTPException(status_code=404, detail="Insufficient data")
            df = merge_sharadar_features(df, conn, symbol)
        feat_df = compute_features(df)
        if feat_df.empty:
            raise HTTPException(status_code=404, detail="No features computed")
        latest = feat_df.iloc[-1]
        state_vector = build_state_vector(latest)
        features = {}
        for col in ALL_FEATURE_COLS:
            if col in latest.index:
                features[col] = _safe_float(latest[col])
        return {
            "symbol": symbol,
            "time": str(latest["time"]),
            "state_vector": state_vector,
            "features": features,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/features/health")
def health():
    return {"status": "ok", "service": "feature-builder"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=FEATURE_BUILDER_PORT)
