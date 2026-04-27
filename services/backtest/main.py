import base64
import io
import json
import hashlib
import logging
import os
from contextlib import asynccontextmanager
from observability import setup_observability
from typing import Optional

import boto3
import numpy as np
import pandas as pd
import psycopg2
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import Response
from pydantic import BaseModel, Field

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
from engine import BacktestEngine, buy_and_hold_policy  # noqa: E402


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

    try:
        model = SB3DQN.load(tmp_path, device="cpu")
    finally:
        os.unlink(tmp_path)

    def policy_fn(state: list) -> int:
        obs = np.array(state, dtype=np.float32).reshape(1, -1)
        action, _ = model.predict(obs, deterministic=True)
        return int(action.item())

    return policy_fn


# ─────────────────────────────────────────
# Chart generation
# ─────────────────────────────────────────
def generate_charts(all_metrics: list[dict]) -> dict:
    """
    Generate equity curve, drawdown, and position charts.
    Returns dict of {chart_name: base64_png_string}.
    Requires matplotlib; skips gracefully if unavailable.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # non-interactive backend
        import matplotlib.pyplot as plt
        import matplotlib.gridspec as gridspec
    except ImportError:
        log.warning("matplotlib not available; skipping chart generation")
        return {}

    charts = {}

    for m in all_metrics:
        symbol = m.get("symbol", "unknown")
        curve  = m.get("equityCurve", [])
        if not curve:
            continue

        navs       = [c["nav"] for c in curve]
        market_nav = [c["market_nav"] for c in curve]
        positions  = [c["position"] for c in curve]

        if not navs:
            continue

        # Drawdown series
        peak = navs[0]
        drawdowns = []
        for n in navs:
            if n > peak:
                peak = n
            drawdowns.append((peak - n) / peak * 100)

        fig = plt.figure(figsize=(12, 8))
        gs  = gridspec.GridSpec(3, 1, figure=fig, height_ratios=[3, 1.5, 1])

        # --- Equity curve ---
        ax1 = fig.add_subplot(gs[0])
        ax1.plot(range(len(navs)), navs, label="Strategy", color="steelblue", linewidth=1.5)
        ax1.plot(range(len(market_nav)), market_nav, label="Buy & Hold", color="orange",
                 linewidth=1.2, linestyle="--")
        # Both formatters guard explicitly against None rather than using
        # `... or 0`, which would silently coerce a nullable contract widening
        # (the way sharpeRatio was widened) into a misleading "0.0%" display.
        sharpe = m.get("sharpeRatio")
        sharpe_str = f"{sharpe:.2f}" if sharpe is not None else "n/a"
        total_ret = m.get("totalReturn")
        ret_str = f"{total_ret * 100:.1f}%" if total_ret is not None else "n/a"
        ax1.set_title(f"{symbol} – Equity Curve  |  Sharpe: {sharpe_str}  "
                      f"Return: {ret_str}")
        ax1.set_ylabel("Portfolio Value ($)")
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # --- Drawdown ---
        ax2 = fig.add_subplot(gs[1], sharex=ax1)
        ax2.fill_between(range(len(drawdowns)), drawdowns, color="crimson", alpha=0.4)
        ax2.plot(range(len(drawdowns)), drawdowns, color="crimson", linewidth=0.8)
        ax2.set_ylabel("Drawdown (%)")
        ax2.invert_yaxis()
        ax2.grid(True, alpha=0.3)

        # --- Position ---
        ax3 = fig.add_subplot(gs[2], sharex=ax1)
        ax3.step(range(len(positions)), positions, color="green", linewidth=0.8)
        ax3.set_yticks([-1, 0, 1])
        ax3.set_yticklabels(["Short", "Flat", "Long"])
        ax3.set_ylabel("Position")
        ax3.set_xlabel("Trading Day")
        ax3.grid(True, alpha=0.3)

        plt.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        charts[symbol] = base64.b64encode(buf.read()).decode()

    return charts


def upload_charts_to_s3(report_id: str, charts: dict) -> dict:
    """Upload PNG charts to MinIO, return {symbol: s3_key} map."""
    s3 = get_s3()
    chart_paths = {}
    for symbol, b64_data in charts.items():
        key  = f"backtests/{report_id}/charts/{symbol}.png"
        data = base64.b64decode(b64_data)
        s3.put_object(Bucket=S3_BUCKET, Key=key, Body=data, ContentType="image/png")
        chart_paths[symbol] = key
    return chart_paths


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

        # Aggregate metrics across symbols. sharpeRatio (and sortinoRatio,
        # profitFactor) can be None per the engine contract — average over
        # the defined entries only, and emit None if every symbol's value
        # is undefined. Mean is computed in plain Python because np.mean
        # raises TypeError on None.
        def _mean_skip_none(xs: list) -> Optional[float]:
            defined = [x for x in xs if x is not None]
            if not defined:
                return None
            return float(sum(defined) / len(defined))

        agg = {
            "symbols": symbols,
            "perSymbol": [{k: v for k, v in m.items() if k != "equityCurve"} for m in all_metrics],
            "avgSharpe":      _mean_skip_none([m["sharpeRatio"] for m in all_metrics]),
            "avgTotalReturn": _mean_skip_none([m["totalReturn"] for m in all_metrics]),
            "avgMaxDrawdown": _mean_skip_none([m["maxDrawdown"] for m in all_metrics]),
            "avgWinRate":     _mean_skip_none([m["winRate"] for m in all_metrics]),
        }

        # Generate and upload charts
        charts     = generate_charts(all_metrics)
        chart_paths = upload_charts_to_s3(report_id, charts) if charts else {}
        agg["chartPaths"] = chart_paths

        # Upload full results to S3
        s3_path = f"backtests/{report_id}/results.json"
        s3 = get_s3()
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_path,
            Body=json.dumps(
                {"metrics": agg, "perSymbol": all_metrics},
                allow_nan=False,
            ).encode(),
        )

        update_backtest_record(report_id, "completed", agg, artifact_path=s3_path)
        sharpe_str = (
            f"{agg['avgSharpe']:.3f}"
            if agg["avgSharpe"] is not None
            else "n/a"
        )
        log.info(f"Backtest {report_id} completed: sharpe={sharpe_str}")

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


@app.get("/backtest/health")
def health():
    return {"status": "ok", "service": "backtest"}


class BacktestRequest(BaseModel):
    name: str
    # Empty symbols list would build `WHERE f.symbol IN ()` and crash the
    # background task with a Postgres syntax error.
    symbols: list[str] = Field(..., min_length=1)
    startDate: str
    endDate: str
    initialCapital: float = Field(default=100_000, gt=0)
    tradingCostBps: float = Field(default=10, ge=0)
    timeCostBps: float = Field(default=1, ge=0)
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


@app.get("/backtest/{report_id}/charts")
def get_backtest_charts(report_id: str):
    """Return chart metadata (S3 paths) for a completed backtest."""
    with get_conn() as conn:
        df = pd.read_sql(
            "SELECT id, status, metrics FROM backtest_report WHERE id=%s",
            conn, params=(report_id,)
        )
    if df.empty:
        raise HTTPException(status_code=404, detail="Backtest not found")
    row = df.iloc[0].to_dict()
    if row["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"Backtest not completed (status={row['status']})")
    metrics = json.loads(row["metrics"]) if isinstance(row["metrics"], str) else (row["metrics"] or {})
    chart_paths = metrics.get("chartPaths", {})
    return {
        "reportId":   report_id,
        "chartPaths": chart_paths,
        "symbols":    list(chart_paths.keys()),
    }


@app.get("/backtest/{report_id}/images/{symbol}")
def get_backtest_image(report_id: str, symbol: str):
    """Proxy-serve a chart PNG from MinIO."""
    with get_conn() as conn:
        df = pd.read_sql(
            "SELECT metrics FROM backtest_report WHERE id=%s", conn, params=(report_id,)
        )
    if df.empty:
        raise HTTPException(status_code=404, detail="Backtest not found")
    metrics = df.iloc[0]["metrics"]
    if isinstance(metrics, str):
        metrics = json.loads(metrics)
    chart_paths = (metrics or {}).get("chartPaths", {})
    s3_key = chart_paths.get(symbol)
    if not s3_key:
        raise HTTPException(status_code=404, detail=f"No chart for symbol {symbol}")
    buf = io.BytesIO()
    get_s3().download_fileobj(S3_BUCKET, s3_key, buf)
    buf.seek(0)
    return Response(content=buf.read(), media_type="image/png")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=BACKTEST_PORT)
