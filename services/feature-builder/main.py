import os
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

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
FEATURE_BUILDER_PORT = int(os.getenv("FEATURE_BUILDER_PORT", "8002"))


def get_conn():
    return psycopg2.connect(DATABASE_URL)


# ─────────────────────────────────────────
# Feature computation
# Mirrors trading_env.py: returns, rsi, macd, atr, stoch, ultosc
# ─────────────────────────────────────────
def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Input: DataFrame with columns [time, symbol, open, high, low, close, volume]
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

    feature_cols = [
        "ret_1d","ret_2d","ret_5d","ret_10d","ret_21d",
        "rsi","macd","atr","stoch","ultosc",
    ]
    df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=feature_cols)
    return df


def build_state_vector(row: pd.Series) -> list[float]:
    """Build the 10-element state vector matching trading_env.py DataSource."""
    from sklearn.preprocessing import scale
    cols = ["ret_1d","ret_2d","ret_5d","ret_10d","ret_21d",
            "rsi","macd","atr","stoch","ultosc"]
    return [float(row[c]) for c in cols]


# ─────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────
def fetch_bars(symbol: str, days: int = 60) -> pd.DataFrame:
    with get_conn() as conn:
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
    return df.sort_values("time").reset_index(drop=True)


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
                   rsi, macd, atr, stoch, ultosc)
                VALUES %s
                ON CONFLICT (time, symbol) DO UPDATE SET
                  ret_1d=EXCLUDED.ret_1d, ret_2d=EXCLUDED.ret_2d,
                  ret_5d=EXCLUDED.ret_5d, ret_10d=EXCLUDED.ret_10d,
                  ret_21d=EXCLUDED.ret_21d, rsi=EXCLUDED.rsi,
                  macd=EXCLUDED.macd, atr=EXCLUDED.atr,
                  stoch=EXCLUDED.stoch, ultosc=EXCLUDED.ultosc
                """,
                [
                    (
                        r["time"], r["symbol"],
                        r["ret_1d"], r["ret_2d"], r["ret_5d"], r["ret_10d"], r["ret_21d"],
                        r["rsi"], r["macd"], r["atr"], r["stoch"], r["ultosc"],
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


@app.post("/features/build")
def build_features(req: BuildFeaturesRequest):
    results = {}
    for symbol in req.symbols:
        try:
            df = fetch_bars(symbol, req.days)
            if len(df) < 22:
                results[symbol] = {"status": "insufficient_data", "rows": len(df)}
                continue
            feat_df = compute_features(df)
            rows = feat_df[[
                "time","ret_1d","ret_2d","ret_5d","ret_10d","ret_21d",
                "rsi","macd","atr","stoch","ultosc",
            ]].assign(symbol=symbol).to_dict("records")
            upsert_features(rows)
            results[symbol] = {"status": "ok", "rows": len(rows)}
            log.info(f"Built {len(rows)} feature rows for {symbol}")
        except Exception as e:
            log.error(f"Feature build failed for {symbol}: {e}")
            results[symbol] = {"status": "error", "error": str(e)}
    return results


@app.get("/features/latest/{symbol}")
def get_latest_features(symbol: str):
    try:
        df = fetch_bars(symbol, 60)
        if len(df) < 22:
            raise HTTPException(status_code=404, detail="Insufficient data")
        feat_df = compute_features(df)
        if feat_df.empty:
            raise HTTPException(status_code=404, detail="No features computed")
        latest = feat_df.iloc[-1]
        state_vector = build_state_vector(latest)
        return {
            "symbol": symbol,
            "time": str(latest["time"]),
            "state_vector": state_vector,
            "features": {
                "ret_1d":  float(latest["ret_1d"]),
                "ret_2d":  float(latest["ret_2d"]),
                "ret_5d":  float(latest["ret_5d"]),
                "ret_10d": float(latest["ret_10d"]),
                "ret_21d": float(latest["ret_21d"]),
                "rsi":     float(latest["rsi"]),
                "macd":    float(latest["macd"]),
                "atr":     float(latest["atr"]),
                "stoch":   float(latest["stoch"]),
                "ultosc":  float(latest["ultosc"]),
            },
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
