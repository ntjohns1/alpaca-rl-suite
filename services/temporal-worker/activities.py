"""
Temporal activities for Alpaca RL Suite.
Each activity is a thin HTTP client calling the relevant microservice.
"""
import asyncio
import logging
import os
import time

import httpx
from temporalio import activity

log = logging.getLogger(__name__)

RL_TRAIN_URL     = os.getenv("RL_TRAIN_URL",    "http://rl-train:8004")
BACKTEST_URL     = os.getenv("BACKTEST_URL",     "http://backtest:8001")
ORDERS_URL       = os.getenv("ORDERS_URL",       "http://orders:3004")
SLACK_WEBHOOK    = os.getenv("SLACK_WEBHOOK_URL", "")

_HTTP_TIMEOUT = httpx.Timeout(30.0)


# ─────────────────────────────────────────
# Training activities
# ─────────────────────────────────────────

@activity.defn
async def start_training_run(params: dict) -> str:
    """POST /train/run → returns run_id."""
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(f"{RL_TRAIN_URL}/train/run", json=params)
        resp.raise_for_status()
        data = resp.json()
        run_id: str = data["runId"]
        log.info(f"[start_training_run] run_id={run_id}")
        return run_id


@activity.defn
async def poll_training_run(params: dict) -> dict:
    """
    Poll GET /train/run/{run_id} until status is completed/failed
    or timeout_s is exceeded.
    """
    run_id: str   = params["run_id"]
    timeout_s: int = params.get("timeout_s", 21600)
    poll_interval  = 30  # seconds

    deadline = time.monotonic() + timeout_s
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        while time.monotonic() < deadline:
            resp = await client.get(f"{RL_TRAIN_URL}/train/run/{run_id}")
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")
            log.info(f"[poll_training_run] run_id={run_id} status={status}")

            if status in ("completed", "failed"):
                return data

            # Heartbeat so Temporal doesn't time out the activity
            activity.heartbeat(f"status={status}")
            await asyncio.sleep(poll_interval)

    return {"status": "timeout", "run_id": run_id, "error": "Training timed out"}


# ─────────────────────────────────────────
# Backtest activity
# ─────────────────────────────────────────

@activity.defn
async def run_backtest(params: dict) -> dict:
    """POST /backtest/run → returns metrics dict."""
    payload = {
        "name":           params.get("name", "workflow-backtest"),
        "symbols":        params.get("symbols", ["AAPL"]),
        "startDate":      params.get("start_date", "2023-01-01"),
        "endDate":        params.get("end_date",   "2023-12-31"),
        "policyS3Path":   params.get("policy_s3_path"),
        "initialCapital": params.get("initial_capital", 100_000),
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(900.0)) as client:
        resp = await client.post(f"{BACKTEST_URL}/backtest/run", json=payload)
        resp.raise_for_status()
        data = resp.json()
        log.info(f"[run_backtest] sharpe={data.get('sharpeRatio')} totalReturn={data.get('totalReturn')}")
        return data


# ─────────────────────────────────────────
# Policy promotion activity
# ─────────────────────────────────────────

@activity.defn
async def promote_policy(params: dict) -> dict:
    """POST /train/run/{run_id}/promote → marks policy as promoted in DB."""
    run_id: str = params["run_id"]
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(
            f"{RL_TRAIN_URL}/train/run/{run_id}/promote",
            json={"artifactPath": params.get("artifact_path")},
        )
        resp.raise_for_status()
        data = resp.json()
        log.info(f"[promote_policy] run_id={run_id} promoted={data}")
        return data


# ─────────────────────────────────────────
# Notification activity
# ─────────────────────────────────────────

@activity.defn
async def notify_slack(params: dict) -> None:
    """Post a message to Slack webhook (no-op if SLACK_WEBHOOK_URL not set)."""
    message: str = params.get("message", "")
    if not SLACK_WEBHOOK:
        log.info(f"[notify_slack] (no webhook) {message}")
        return
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        try:
            await client.post(SLACK_WEBHOOK, json={"text": message})
        except Exception as exc:
            log.warning(f"[notify_slack] failed: {exc}")
