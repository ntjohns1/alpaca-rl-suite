"""
RL Training Service
Trains agents via Stable-Baselines3 DQN (double-DQN by default).
Keeps the same TradingEnvironment gymnasium interface and S3/DB plumbing.
"""
import os
import io
import json
import hashlib
import logging
from contextlib import asynccontextmanager
from observability import setup_observability
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
import psycopg2
import boto3
import torch
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.responses import Response
from pydantic import BaseModel
from stable_baselines3 import DQN
from stable_baselines3.common.callbacks import BaseCallback, EvalCallback
from stable_baselines3.common.monitor import Monitor

from trading_env import TradingEnvironment

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

DATABASE_URL  = os.environ["DATABASE_URL"]
S3_ENDPOINT   = os.getenv("S3_ENDPOINT", "http://localhost:9000")
S3_BUCKET     = os.getenv("S3_BUCKET", "alpaca-rl-artifacts")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "minioadmin")
RL_TRAIN_PORT = int(os.getenv("RL_TRAIN_PORT", "8004"))


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
# Data loading
# ─────────────────────────────────────────
def load_bars(symbol: str) -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql(
            """SELECT time::date as date, open::float, high::float,
                      low::float, close::float, volume::bigint
               FROM bar_1d WHERE symbol=%s ORDER BY time""",
            conn, params=(symbol,),
        )
    df = df.set_index("date")
    return df


# ─────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────
def create_run(name: str, config: dict) -> str:
    config_hash = hashlib.sha256(
        json.dumps(config, sort_keys=True).encode()
    ).hexdigest()[:12]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO training_run (name, config_hash, config, status, started_at)
                   VALUES (%s,%s,%s,'running',NOW()) RETURNING id""",
                (name, config_hash, json.dumps(config)),
            )
            run_id = str(cur.fetchone()[0])
        conn.commit()
    return run_id


def update_run(run_id: str, status: str, metrics: dict, artifact_path: str = None, error: str = None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE training_run
                   SET status=%s, metrics=%s, artifact_path=%s, error=%s,
                       completed_at=CASE WHEN %s IN ('completed','failed') THEN NOW() ELSE completed_at END
                   WHERE id=%s""",
                (status, json.dumps(metrics), artifact_path, error, status, run_id),
            )
        conn.commit()


def save_policy_bundle(run_id: str, s3_path: str, config: dict, metrics: dict) -> str:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO policy_bundle (training_run_id, name, version, s3_path, config, metrics)
                   VALUES (%s,%s,'1.0',%s,%s,%s) RETURNING id""",
                (run_id, config["name"], s3_path,
                 json.dumps(config), json.dumps(metrics)),
            )
            bundle_id = str(cur.fetchone()[0])
        conn.commit()
    return bundle_id


# ─────────────────────────────────────────
# Episode metrics callback (SB3)
# ─────────────────────────────────────────
class EpisodeMetricsCallback(BaseCallback):
    """Logs per-episode rewards from the Monitor wrapper."""

    def __init__(self, run_id: str, log_interval: int = 50):
        super().__init__()
        self.run_id = run_id
        self.log_interval = log_interval
        self.episode_metrics: list[dict] = []

    def _on_step(self) -> bool:
        for info in self.locals.get("infos", []):
            if "episode" in info:
                ep_num = len(self.episode_metrics) + 1
                self.episode_metrics.append({
                    "episode":     ep_num,
                    "totalReward": round(float(info["episode"]["r"]), 4),
                    "steps":       int(info["episode"]["l"]),
                    "epsilon":     round(float(self.model.exploration_rate), 4),
                })
                if ep_num % self.log_interval == 0:
                    recent = self.episode_metrics[-self.log_interval:]
                    avg_r = np.mean([m["totalReward"] for m in recent])
                    log.info(
                        f"[{self.run_id}] ep={ep_num} avg_reward={avg_r:.4f} "
                        f"eps={self.episode_metrics[-1]['epsilon']:.4f}"
                    )
        return True


# ─────────────────────────────────────────
# Training (SB3 DQN)
# ─────────────────────────────────────────
def train(run_id: str, config: dict):
    try:
        symbols      = config["symbols"]
        total_steps  = config.get("totalTimesteps", 500_000)
        trading_days = config.get("tradingDays", 252)
        trading_cost = config.get("tradingCostBps", 10) / 10_000
        time_cost    = config.get("timeCostBps", 1) / 10_000
        seed         = config.get("seed")

        # Load data for first symbol (single-symbol MVP)
        symbol = symbols[0]
        log.info(f"[{run_id}] Loading bars for {symbol}")
        df = load_bars(symbol)
        if len(df) < 300:
            raise ValueError(f"Insufficient data for {symbol}: {len(df)} bars")

        # Build env (Monitor wrapper gives episode reward/length in infos)
        raw_env = TradingEnvironment(
            df=df,
            trading_days=trading_days,
            trading_cost_bps=trading_cost,
            time_cost_bps=time_cost,
        )
        env = Monitor(raw_env)
        state_dim = env.observation_space.shape[0]

        # SB3 DQN — uses double-DQN (target network) by default
        model = DQN(
            policy="MlpPolicy",
            env=env,
            learning_rate=config.get("learningRate", 1e-4),
            buffer_size=config.get("replayCapacity", 100_000),
            learning_starts=config.get("learningStarts", 1000),
            batch_size=config.get("batchSize", 256),
            gamma=config.get("gamma", 0.99),
            target_update_interval=config.get("tau", 100),
            exploration_fraction=config.get("explorationFraction", 0.3),
            exploration_initial_eps=config.get("epsilonStart", 1.0),
            exploration_final_eps=config.get("epsilonEnd", 0.05),
            policy_kwargs={"net_arch": config.get("architecture", [256, 256])},
            verbose=0,
            seed=seed,
        )

        cb = EpisodeMetricsCallback(run_id, log_interval=50)
        model.learn(total_timesteps=total_steps, callback=cb, progress_bar=False)

        # Save SB3 model (zip) locally then upload to S3
        ckpt_path = f"/tmp/{run_id}_model"
        model.save(ckpt_path)

        s3_path = f"models/{run_id}/policy_best.zip"
        s3 = get_s3()
        try:
            with open(f"{ckpt_path}.zip", "rb") as f:
                s3.put_object(Bucket=S3_BUCKET, Key=s3_path, Body=f.read())
        finally:
            # Clean up temporary files
            try:
                os.unlink(f"{ckpt_path}.zip")
            except OSError:
                pass

        # Upload episode history
        hist_path = f"models/{run_id}/episode_history.json"
        s3.put_object(
            Bucket=S3_BUCKET, Key=hist_path,
            Body=json.dumps(cb.episode_metrics).encode(),
        )

        ep_rewards = [m["totalReward"] for m in cb.episode_metrics]
        final_metrics = {
            "symbol":         symbol,
            "totalTimesteps": total_steps,
            "totalEpisodes":  len(cb.episode_metrics),
            "meanReward":     round(float(np.mean(ep_rewards[-50:])) if ep_rewards else 0.0, 4),
            "maxReward":      round(float(np.max(ep_rewards)) if ep_rewards else 0.0, 4),
            "finalEpsilon":   round(float(model.exploration_rate), 4),
            "stateDim":       state_dim,
            "framework":      "stable-baselines3",
            "episodeHistory": cb.episode_metrics[-100:],
        }

        config_for_bundle = {**config, "state_dim": state_dim, "framework": "sb3"}
        save_policy_bundle(run_id, s3_path, config_for_bundle, final_metrics)
        update_run(run_id, "completed", final_metrics, artifact_path=s3_path)

        log.info(
            f"[{run_id}] Training complete. "
            f"mean_reward={final_metrics['meanReward']:.4f} "
            f"episodes={final_metrics['totalEpisodes']}"
        )

    except Exception as e:
        log.error(f"[{run_id}] Training failed: {e}", exc_info=True)
        update_run(run_id, "failed", {}, error=str(e))


# ─────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("RL Training service started")
    yield


app = FastAPI(title="RL Training Service", lifespan=lifespan)
setup_observability(app, "rl-train")


class TrainingRequest(BaseModel):
    name: str
    symbols: list[str]
    totalTimesteps: int = 500_000
    tradingDays: int = 252
    tradingCostBps: float = 10
    timeCostBps: float = 1
    gamma: float = 0.99
    learningRate: float = 1e-4
    batchSize: int = 256
    replayCapacity: int = 100_000
    learningStarts: int = 1000
    architecture: list[int] = [256, 256]
    tau: int = 100
    explorationFraction: float = 0.3
    epsilonStart: float = 1.0
    epsilonEnd: float = 0.05
    seed: Optional[int] = None
    datasetId: Optional[str] = None


@app.post("/rl/train")
def start_training(req: TrainingRequest, background_tasks: BackgroundTasks):
    config = req.model_dump()
    run_id = create_run(req.name, config)
    background_tasks.add_task(train, run_id, config)
    return {"runId": run_id, "status": "running", "name": req.name}


@app.get("/rl/runs")
def list_runs(limit: int = 50):
    with get_conn() as conn:
        df = pd.read_sql(
            "SELECT id,name,status,config_hash,started_at,completed_at FROM training_run ORDER BY started_at DESC LIMIT %s",
            conn, params=(limit,),
        )
    return df.to_dict("records")


@app.get("/rl/runs/{run_id}")
def get_run(run_id: str):
    with get_conn() as conn:
        df = pd.read_sql(
            "SELECT * FROM training_run WHERE id=%s", conn, params=(run_id,)
        )
    if df.empty:
        raise HTTPException(status_code=404, detail="Run not found")
    row = df.iloc[0].to_dict()
    if isinstance(row.get("metrics"), str):
        row["metrics"] = json.loads(row["metrics"])
    return row


@app.get("/rl/policies")
def list_policies(
    promoted_only: bool = False,
    approval_status: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    """List policy bundles with optional filters."""
    conditions = []
    params: list = []
    if promoted_only:
        conditions.append("promoted = TRUE")
    if approval_status:
        conditions.append("approval_status = %s")
        params.append(approval_status)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    with get_conn() as conn:
        df = pd.read_sql(
            f"""SELECT id, name, version, promoted, approval_status, approved_by,
                       approved_at, created_at, s3_path, metrics
                FROM policy_bundle {where}
                ORDER BY created_at DESC LIMIT %s""",
            conn, params=params,
        )
    records = df.to_dict("records")
    for r in records:
        if isinstance(r.get("metrics"), str):
            r["metrics"] = json.loads(r["metrics"])
    return records


@app.get("/rl/policies/{policy_id}")
def get_policy(policy_id: str):
    """Get full policy bundle details."""
    with get_conn() as conn:
        df = pd.read_sql("SELECT * FROM policy_bundle WHERE id=%s", conn, params=(policy_id,))
    if df.empty:
        raise HTTPException(status_code=404, detail="Policy not found")
    row = df.iloc[0].to_dict()
    for key in ("config", "metrics"):
        if isinstance(row.get(key), str):
            row[key] = json.loads(row[key])
    return row


@app.post("/rl/policies/{policy_id}/approve")
def approve_policy(policy_id: str, approved_by: str = "admin"):
    """Approve a policy for promotion (sets approval_status to approved)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE policy_bundle
                   SET approval_status='approved', approved_by=%s, approved_at=NOW()
                   WHERE id=%s RETURNING id""",
                (approved_by, policy_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Policy not found")
        conn.commit()
    return {"policyId": policy_id, "approvalStatus": "approved", "approvedBy": approved_by}


@app.post("/rl/policies/{policy_id}/reject")
def reject_policy(policy_id: str, reason: Optional[str] = None, rejected_by: str = "admin"):
    """Reject a policy from promotion."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE policy_bundle
                   SET approval_status='rejected', rejection_reason=%s
                   WHERE id=%s RETURNING id""",
                (reason, policy_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Policy not found")
        conn.commit()
    return {"policyId": policy_id, "approvalStatus": "rejected", "reason": reason}


@app.post("/rl/policies/{policy_id}/promote")
def promote_policy(policy_id: str, promoted_by: str = "admin"):
    """Promote an approved policy to production. Requires approval_status=approved."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT approval_status FROM policy_bundle WHERE id=%s", (policy_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Policy not found")
            approval_status = row[0] if row else None
            if approval_status == "rejected":
                raise HTTPException(status_code=400, detail="Cannot promote a rejected policy")
            if approval_status != "approved":
                raise HTTPException(
                    status_code=400,
                    detail=f"Policy must be approved before promotion (current status: {approval_status})"
                )
            cur.execute(
                """UPDATE policy_bundle
                   SET promoted=TRUE, promoted_at=NOW(), promoted_by=%s
                   WHERE id=%s""",
                (promoted_by, policy_id),
            )
        conn.commit()
    return {"policyId": policy_id, "promoted": True, "promotedBy": promoted_by}


@app.get("/rl/policies/{policy_id}/download")
def download_policy(policy_id: str):
    """Stream the policy .zip file directly from MinIO."""
    with get_conn() as conn:
        df = pd.read_sql("SELECT name, s3_path FROM policy_bundle WHERE id=%s", conn, params=(policy_id,))
    if df.empty:
        raise HTTPException(status_code=404, detail="Policy not found")
    row   = df.iloc[0]
    s3    = get_s3()
    buf   = io.BytesIO()
    try:
        s3.download_fileobj(S3_BUCKET, row["s3_path"], buf)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not fetch from storage: {e}")
    buf.seek(0)
    filename = f"{row['name'].replace(' ', '_')}.zip"
    return Response(
        content=buf.read(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.delete("/rl/policies/{policy_id}", status_code=204)
def delete_policy(policy_id: str):
    """Delete a policy bundle record (does not remove S3 file)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM policy_bundle WHERE id=%s RETURNING id", (policy_id,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Policy not found")
        conn.commit()


@app.get("/rl/train/health")
def health():
    return {"status": "ok", "service": "rl-train", "cuda": torch.cuda.is_available()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=RL_TRAIN_PORT)
