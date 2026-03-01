"""
Temporal Worker for Alpaca RL Suite.
Registers TrainingWorkflow, BacktestWorkflow and all activities.
Also exposes a minimal FastAPI health + trigger endpoint.
"""
import asyncio
import logging
import os

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from temporalio.client import Client
from temporalio.worker import Worker

from workflows import TrainingWorkflow, BacktestWorkflow
from activities import (
    start_training_run,
    poll_training_run,
    run_backtest,
    promote_policy,
    notify_slack,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

TEMPORAL_ADDRESS  = os.getenv("TEMPORAL_ADDRESS",  "temporal:7233")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")
TASK_QUEUE        = os.getenv("TEMPORAL_TASK_QUEUE", "alpaca-rl-main")
WORKER_PORT       = int(os.getenv("TEMPORAL_WORKER_PORT", "8010"))

# ─────────────────────────────────────────
# FastAPI app (health + manual trigger)
# ─────────────────────────────────────────
app = FastAPI(title="Temporal Worker", docs_url="/docs")


class TrainRequest(BaseModel):
    name: str
    symbols: list[str] = ["AAPL"]
    totalTimesteps: int = 100_000
    backtest_start: str = "2023-01-01"
    backtest_end: str   = "2023-12-31"
    sharpe_threshold: float = 0.5


class BacktestRequest(BaseModel):
    name: str
    symbols: list[str] = ["AAPL"]
    policy_s3_path: str
    start_date: str = "2023-01-01"
    end_date: str   = "2023-12-31"


_temporal_client: Client | None = None


async def get_client() -> Client:
    global _temporal_client
    if _temporal_client is None:
        _temporal_client = await Client.connect(
            TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE
        )
    return _temporal_client


@app.get("/temporal/health")
async def health():
    return {"status": "ok", "service": "temporal-worker", "taskQueue": TASK_QUEUE}


@app.post("/temporal/train")
async def trigger_training(req: TrainRequest):
    """Manually trigger a TrainingWorkflow."""
    client = await get_client()
    handle = await client.start_workflow(
        TrainingWorkflow.run,
        req.model_dump(),
        id=f"train-{req.name}-{asyncio.get_event_loop().time():.0f}",
        task_queue=TASK_QUEUE,
    )
    return {"workflowId": handle.id, "runId": handle.result_run_id}


@app.post("/temporal/backtest")
async def trigger_backtest(req: BacktestRequest):
    """Manually trigger a BacktestWorkflow."""
    client = await get_client()
    handle = await client.start_workflow(
        BacktestWorkflow.run,
        req.model_dump(),
        id=f"backtest-{req.name}-{asyncio.get_event_loop().time():.0f}",
        task_queue=TASK_QUEUE,
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
    log.info(f"Temporal worker listening on task queue '{TASK_QUEUE}'")
    await worker.run()


async def main():
    # Start worker + uvicorn concurrently
    config = uvicorn.Config(app, host="0.0.0.0", port=WORKER_PORT, log_level="info")
    server = uvicorn.Server(config)
    await asyncio.gather(run_worker(), server.serve())


if __name__ == "__main__":
    asyncio.run(main())
