"""
RL Inference Service
Loads a promoted DDQN policy bundle from MinIO and serves low-latency action predictions.
POST /infer/action  → {action: 0|1|2, actionLabel: SHORT|HOLD|LONG, qValues, latencyMs}
"""
import io
import os
import time
import logging
from contextlib import asynccontextmanager
from observability import setup_observability
from typing import Optional

import tempfile
import numpy as np
import psycopg2
import boto3
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from stable_baselines3 import DQN

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

DATABASE_URL  = os.environ["DATABASE_URL"]
S3_ENDPOINT   = os.getenv("S3_ENDPOINT", "http://localhost:9000")
S3_BUCKET     = os.getenv("S3_BUCKET", "alpaca-rl-artifacts")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "minioadmin")
RL_INFER_PORT = int(os.getenv("RL_INFER_PORT", "8005"))

ACTION_LABELS = ["SHORT", "HOLD", "LONG"]


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
# In-process policy cache
# ─────────────────────────────────────────
class PolicyCache:
    def __init__(self):
        self._policies: dict[str, dict] = {}  # policy_id -> {model, config}
        self._active_id: Optional[str] = None

    def load(self, policy_id: str, s3_path: str) -> None:
        s3 = get_s3()
        buf = io.BytesIO()
        s3.download_fileobj(S3_BUCKET, s3_path, buf)
        buf.seek(0)
        # SB3 saves as .zip — write to a temp file then load
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            f.write(buf.read())
            tmp_path = f.name
        model = DQN.load(tmp_path, device="cpu")
        self._policies[policy_id] = {"model": model}
        log.info(f"Loaded SB3 policy {policy_id} from {s3_path}")

    def infer(self, policy_id: str, state: list[float]) -> tuple[int, list[float]]:
        entry = self._policies.get(policy_id)
        if entry is None:
            raise KeyError(f"Policy {policy_id} not loaded")
        model: DQN = entry["model"]
        obs = np.array(state, dtype=np.float32).reshape(1, -1)
        action, _state = model.predict(obs, deterministic=True)
        # Extract Q-values from the policy network
        import torch
        with torch.no_grad():
            obs_t = model.policy.obs_to_tensor(obs)[0]
            q_vals = model.policy.q_net(obs_t).squeeze(0).tolist()
        return int(action.item()), q_vals

    def set_active(self, policy_id: str):
        self._active_id = policy_id

    def get_active(self) -> Optional[str]:
        return self._active_id

    def loaded_ids(self) -> list[str]:
        return list(self._policies.keys())


CACHE = PolicyCache()


def load_promoted_policy():
    """Load the currently promoted policy at startup."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, s3_path FROM policy_bundle WHERE promoted=TRUE ORDER BY promoted_at DESC LIMIT 1"
                )
                row = cur.fetchone()
        if row:
            policy_id, s3_path = str(row[0]), row[1]
            CACHE.load(policy_id, s3_path)
            CACHE.set_active(policy_id)
            log.info(f"Loaded promoted policy {policy_id}")
        else:
            log.warning("No promoted policy found — inference will use fallback (HOLD)")
    except Exception as e:
        log.warning(f"Could not load promoted policy: {e}")


# ─────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    load_promoted_policy()
    log.info("RL Inference service ready")
    yield


app = FastAPI(title="RL Inference Service", lifespan=lifespan)
setup_observability(app, "rl-infer")


class InferRequest(BaseModel):
    symbol: str
    state: list[float]
    policyId: Optional[str] = None
    traceId: Optional[str] = None


@app.post("/infer/action")
def infer_action(req: InferRequest):
    t0 = time.perf_counter()

    policy_id = req.policyId or CACHE.get_active()
    if policy_id is None:
        # Fallback: always HOLD when no policy loaded
        return {
            "symbol":      req.symbol,
            "action":      1,
            "actionLabel": "HOLD",
            "qValues":     None,
            "policyId":    "fallback",
            "latencyMs":   0.0,
        }

    if policy_id not in CACHE.loaded_ids():
        # Try to load on-demand from DB
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT s3_path FROM policy_bundle WHERE id=%s", (policy_id,))
                    row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Policy {policy_id} not found")
            CACHE.load(policy_id, row[0])
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to load policy: {e}")

    try:
        action, q_values = CACHE.infer(policy_id, req.state)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Inference error: {e}")

    latency_ms = (time.perf_counter() - t0) * 1000

    return {
        "symbol":      req.symbol,
        "action":      action,
        "actionLabel": ACTION_LABELS[action],
        "qValues":     q_values,
        "policyId":    policy_id,
        "latencyMs":   round(latency_ms, 3),
    }


@app.post("/infer/load/{policy_id}")
def load_policy(policy_id: str, activate: bool = False):
    """Manually load a policy into the cache."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT s3_path FROM policy_bundle WHERE id=%s", (policy_id,))
                row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Policy not found")
        CACHE.load(policy_id, row[0])
        if activate:
            CACHE.set_active(policy_id)
        return {"policyId": policy_id, "loaded": True, "active": activate}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/infer/active")
def get_active():
    return {
        "activePolicyId": CACHE.get_active(),
        "loadedPolicies": CACHE.loaded_ids(),
    }


@app.post("/infer/activate/{policy_id}")
def activate_policy(policy_id: str):
    if policy_id not in CACHE.loaded_ids():
        raise HTTPException(status_code=400, detail="Policy not loaded. Call /infer/load first.")
    CACHE.set_active(policy_id)
    return {"activePolicyId": policy_id}


@app.get("/infer/health")
def health():
    return {
        "status":         "ok",
        "service":        "rl-infer",
        "activePolicyId": CACHE.get_active(),
        "loadedPolicies": len(CACHE.loaded_ids()),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=RL_INFER_PORT)
