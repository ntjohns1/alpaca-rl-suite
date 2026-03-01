import os
import io
import json
import hashlib
import logging
from contextlib import asynccontextmanager
from observability import setup_observability
from datetime import datetime
from typing import Optional

import pandas as pd
import numpy as np
import pyarrow.parquet as pq
import boto3
import psycopg2
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

DATABASE_URL  = os.environ["DATABASE_URL"]
S3_ENDPOINT   = os.getenv("S3_ENDPOINT", "http://localhost:9000")
S3_BUCKET     = os.getenv("S3_BUCKET", "alpaca-rl-artifacts")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "minioadmin")
BACKTEST_PORT = int(os.getenv("BACKTEST_PORT", "8001"))


def get_s3():
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
    )


def get_conn():
    return psycopg2.connect(DATABASE_URL)


# ─────────────────────────────────────────
# Engine + baseline policies (imported from engine.py)
# ─────────────────────────────────────────
from engine import BacktestEngine, buy_and_hold_policy, random_policy  # noqa: E402


# ─────────────────────────────────────────
# Policy loading helper
# ─────────────────────────────────────────
def load_policy_from_s3(policy_s3_path: str):
    """Load an SB3 DQN .zip policy from S3 and return a callable."""
    import tempfile
    from stable_baselines3 import DQN as SB3DQN

    s3 = get_s3()
    buf = io.BytesIO()
    s3.download_fileobj(S3_BUCKET, policy_s3_path, buf)
    buf.seek(0)

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
        f.write(buf.read())
        tmp_path = f.name

    model = SB3DQN.load(tmp_path, device="cpu")

    def policy_fn(state: list) -> int:
        obs = np.array(state, dtype=np.float32).reshape(1, -1)
        action, _ = model.predict(obs, deterministic=True)
        return int(action.item())

    return policy_fn


def buy_and_hold_policy(_state) -> int:
    return 2  # Always LONG


def random_policy(_state) -> int:
    return np.random.randint(0, 3)


# ─────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────
def create_backtest_record(config: dict) -> str:
    config_hash = hashlib.sha256(
        json.dumps(config, sort_keys=True).encode()
    ).hexdigest()[:12]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO backtest_report (name, config, config_hash, status)
                   VALUES (%s, %s, %s, 'running') RETURNING id""",
                (config["name"], json.dumps(config), config_hash),
            )
            report_id = str(cur.fetchone()[0])
        conn.commit()
    return report_id


def update_backtest_record(report_id: str, status: str, metrics: dict, artifact_path: str = None, error: str = None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE backtest_report
                   SET status=%s, metrics=%s, artifact_path=%s, error=%s
                   WHERE id=%s""",
                (status, json.dumps(metrics), artifact_path, error, report_id),
            )
        conn.commit()


def fetch_features_for_backtest(symbols: list[str], start_date: str, end_date: str) -> pd.DataFrame:
    with get_conn() as conn:
        ph = ",".join(["%s"] * len(symbols))
        df = pd.read_sql(
            f"""
            SELECT f.time, f.symbol,
                   f.ret_1d, f.ret_2d, f.ret_5d, f.ret_10d, f.ret_21d,
                   f.rsi, f.macd, f.atr, f.stoch, f.ultosc,
                   b.close::float as close
            FROM feature_row f
            JOIN bar_1d b USING (time, symbol)
            WHERE f.symbol IN ({ph})
              AND f.time BETWEEN %s AND %s
            ORDER BY f.symbol, f.time
            """,
            conn,
            params=(*symbols, start_date, end_date),
        )
    return df


# ─────────────────────────────────────────
# Background task
# ─────────────────────────────────────────
def run_backtest_task(report_id: str, config: dict):
    try:
        symbols    = config["symbols"]
        start_date = config["startDate"]
        end_date   = config["endDate"]

        df = fetch_features_for_backtest(symbols, start_date, end_date)
        if df.empty:
            update_backtest_record(report_id, "failed", {}, error="No data found")
            return

        engine = BacktestEngine(
            initial_capital=config.get("initialCapital", 100_000),
            trading_cost_bps=config.get("tradingCostBps", 10),
            time_cost_bps=config.get("timeCostBps", 1),
            seed=config.get("seed"),
        )

        # Load policy
        policy_id = config.get("policyId")
        if policy_id:
            with get_conn() as conn:
                row = pd.read_sql(
                    "SELECT s3_path FROM policy_bundle WHERE id=%s", conn, params=(policy_id,)
                )
            if not row.empty:
                policy_fn = load_policy_from_s3(row.iloc[0]["s3_path"])
            else:
                policy_fn = buy_and_hold_policy
        else:
            policy_fn = buy_and_hold_policy

        # Run per-symbol, aggregate
        all_metrics = []
        for symbol in symbols:
            sym_df = df[df["symbol"] == symbol].copy()
            if len(sym_df) < 22:
                continue
            m = engine.run(sym_df, policy_fn)
            m["symbol"] = symbol
            all_metrics.append(m)

        if not all_metrics:
            update_backtest_record(report_id, "failed", {}, error="Insufficient data for all symbols")
            return

        # Aggregate metrics across symbols
        agg = {
            "symbols": symbols,
            "perSymbol": [{k: v for k, v in m.items() if k != "equityCurve"} for m in all_metrics],
            "avgSharpe":      np.mean([m["sharpeRatio"] for m in all_metrics]),
            "avgTotalReturn": np.mean([m["totalReturn"] for m in all_metrics]),
            "avgMaxDrawdown": np.mean([m["maxDrawdown"] for m in all_metrics]),
            "avgWinRate":     np.mean([m["winRate"] for m in all_metrics]),
        }

        # Upload equity curves to S3
        s3_path = f"backtests/{report_id}/results.json"
        s3 = get_s3()
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_path,
            Body=json.dumps({"metrics": agg, "perSymbol": all_metrics}).encode(),
        )

        update_backtest_record(report_id, "completed", agg, artifact_path=s3_path)
        log.info(f"Backtest {report_id} completed: sharpe={agg['avgSharpe']:.3f}")

    except Exception as e:
        log.error(f"Backtest {report_id} failed: {e}")
        update_backtest_record(report_id, "failed", {}, error=str(e))


# ─────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Backtest service started")
    yield


app = FastAPI(title="Backtest Service", lifespan=lifespan)
setup_observability(app, "backtest")


class BacktestRequest(BaseModel):
    name: str
    symbols: list[str]
    startDate: str
    endDate: str
    initialCapital: float = 100_000
    tradingCostBps: float = 10
    timeCostBps: float = 1
    policyId: Optional[str] = None
    seed: Optional[int] = None


@app.post("/backtest/run")
def run_backtest(req: BacktestRequest, background_tasks: BackgroundTasks):
    config = req.model_dump()
    report_id = create_backtest_record(config)
    background_tasks.add_task(run_backtest_task, report_id, config)
    return {"reportId": report_id, "status": "running"}


@app.get("/backtest/{report_id}")
def get_backtest(report_id: str):
    with get_conn() as conn:
        df = pd.read_sql(
            "SELECT * FROM backtest_report WHERE id=%s", conn, params=(report_id,)
        )
    if df.empty:
        raise HTTPException(status_code=404, detail="Backtest not found")
    row = df.iloc[0].to_dict()
    if isinstance(row.get("metrics"), str):
        row["metrics"] = json.loads(row["metrics"])
    return row


@app.get("/backtest")
def list_backtests(limit: int = 50):
    with get_conn() as conn:
        df = pd.read_sql(
            "SELECT id,name,status,config_hash,created_at FROM backtest_report ORDER BY created_at DESC LIMIT %s",
            conn, params=(limit,),
        )
    return df.to_dict("records")


@app.get("/backtest/health")
def health():
    return {"status": "ok", "service": "backtest"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=BACKTEST_PORT)
