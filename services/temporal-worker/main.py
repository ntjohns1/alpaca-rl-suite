"""
Temporal Worker for Alpaca RL Suite.
Registers TrainingWorkflow, BacktestWorkflow and all activities.
Also exposes a minimal FastAPI health + trigger endpoint.
"""
import asyncio
import logging
import os
import uuid

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.worker import Worker

from workflows import TrainingWorkflow, BacktestWorkflow
from activities import (
    KC_CLIENT_ID,
    KC_CLIENT_SECRET,
    KEYCLOAK_URL,
    start_training_run,
    poll_training_run,
    run_backtest,
    promote_policy,
    notify_slack,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

TEMPORAL_ADDRESS   = os.getenv("TEMPORAL_ADDRESS",    "temporal:7233")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE",  "default")
TASK_QUEUE         = os.getenv("TEMPORAL_TASK_QUEUE", "alpaca-rl-main")
WORKER_PORT        = int(os.getenv("TEMPORAL_WORKER_PORT", "8010"))

# ─────────────────────────────────────────
# FastAPI app (health + manual trigger)
# ─────────────────────────────────────────
app = FastAPI(title="Temporal Worker", docs_url="/docs")

_worker_healthy = False


class TrainRequest(BaseModel):
    name: str
    symbols: list[str] = ["AAPL"]
    totalTimesteps: int = 100_000
    backtest_start: str
    backtest_end: str
    sharpe_threshold: float = 0.5
    idempotency_key: str | None = None


class BacktestRequest(BaseModel):
    name: str
    symbols: list[str] = ["AAPL"]
    policy_s3_path: str
    start_date: str
    end_date: str
    idempotency_key: str | None = None


_temporal_client: Client | None = None
_client_lock = asyncio.Lock()


async def get_client() -> Client:
    global _temporal_client
    async with _client_lock:
        if _temporal_client is None:
            _temporal_client = await Client.connect(
                TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE
            )
    return _temporal_client


@app.get("/temporal/health")
async def health():
    if not _worker_healthy:
        raise HTTPException(status_code=503, detail="Temporal worker not connected")
    return {"status": "ok", "service": "temporal-worker", "taskQueue": TASK_QUEUE}


@app.post("/temporal/train")
async def trigger_training(req: TrainRequest):
    """Manually trigger a TrainingWorkflow."""
    client = await get_client()
    key = req.idempotency_key or str(uuid.uuid4())
    handle = await client.start_workflow(
        TrainingWorkflow.run,
        req.model_dump(),
        id=f"train-{req.name}-{key}",
        task_queue=TASK_QUEUE,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
    )
    return {"workflowId": handle.id, "runId": handle.result_run_id}


@app.post("/temporal/backtest")
async def trigger_backtest(req: BacktestRequest):
    """Manually trigger a BacktestWorkflow."""
    client = await get_client()
    key = req.idempotency_key or str(uuid.uuid4())
    handle = await client.start_workflow(
        BacktestWorkflow.run,
        req.model_dump(),
        id=f"backtest-{req.name}-{key}",
        task_queue=TASK_QUEUE,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
    )
    return {"workflowId": handle.id, "runId": handle.result_run_id}


@app.get("/temporal/workflow/{workflow_id}")
async def get_workflow_status(workflow_id: str):
    """Query a workflow's status."""
    client = await get_client()
    handle = client.get_workflow_handle(workflow_id)
    try:
        desc = await handle.describe()
        return {
            "workflowId": workflow_id,
            "status": str(desc.status),
            "startTime": str(desc.start_time),
        }
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ─────────────────────────────────────────
# Worker runner
# ─────────────────────────────────────────
async def run_worker():
    global _worker_healthy
    client = await get_client()
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[TrainingWorkflow, BacktestWorkflow],
        activities=[
            start_training_run,
            poll_training_run,
            run_backtest,
            promote_policy,
            notify_slack,
        ],
    )
    _worker_healthy = True
    log.info(f"Temporal worker listening on task queue '{TASK_QUEUE}'")
    try:
        await worker.run()
    finally:
        _worker_healthy = False


def _check_config() -> None:
    """Fail fast if required credentials are missing."""
    missing = []
    if not KEYCLOAK_URL:
        missing.append("KEYCLOAK_URL")
    if not KC_CLIENT_ID:
        missing.append("KC_SERVICE_CLIENT_ID")
    if not KC_CLIENT_SECRET:
        missing.append("KC_SERVICE_CLIENT_SECRET")
    if missing:
        raise RuntimeError(
            f"Missing required env vars: {', '.join(missing)}. "
            "Create a 'temporal-worker' service-account client (confidential, "
            "client_credentials grant) in your Keycloak realm and set these vars."
        )


async def main():
    _check_config()
    config = uvicorn.Config(app, host="0.0.0.0", port=WORKER_PORT, log_level="info")
    server = uvicorn.Server(config)
    await asyncio.gather(run_worker(), server.serve())


if __name__ == "__main__":
    asyncio.run(main())
