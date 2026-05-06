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

KEYCLOAK_URL    = os.getenv("KEYCLOAK_URL",    "https://auth.nelsonjohns.com")
KEYCLOAK_REALM  = os.getenv("KEYCLOAK_REALM",  "alpaca-rl-suite")
KC_CLIENT_ID     = os.getenv("KC_SERVICE_CLIENT_ID",     "")
KC_CLIENT_SECRET = os.getenv("KC_SERVICE_CLIENT_SECRET", "")

_HTTP_TIMEOUT = httpx.Timeout(30.0)

# ── Token cache ───────────────────────────────────────────────────────────────

_token_lock  = asyncio.Lock()
_token_cache: dict = {"token": None, "expires_at": 0.0}


async def _auth_headers() -> dict:
    """Return Authorization header with a valid service-account Bearer token."""
    async with _token_lock:
        if _token_cache["token"] and time.monotonic() < _token_cache["expires_at"] - 30:
            return {"Authorization": f"Bearer {_token_cache['token']}"}

        token_url = (
            f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}"
            "/protocol/openid-connect/token"
        )
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.post(token_url, data={
                "grant_type":    "client_credentials",
                "client_id":     KC_CLIENT_ID,
                "client_secret": KC_CLIENT_SECRET,
            })
            resp.raise_for_status()
            data = resp.json()

        _token_cache["token"]      = data["access_token"]
        _token_cache["expires_at"] = time.monotonic() + data.get("expires_in", 300)
        return {"Authorization": f"Bearer {_token_cache['token']}"}


# ─────────────────────────────────────────
# Training activities
# ─────────────────────────────────────────

@activity.defn
async def start_training_run(params: dict) -> str:
    """POST /rl/train → returns run_id."""
    headers = await _auth_headers()
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, headers=headers) as client:
        resp = await client.post(f"{RL_TRAIN_URL}/rl/train", json=params)
        resp.raise_for_status()
        data = resp.json()
        run_id: str = data["runId"]
        log.info(f"[start_training_run] run_id={run_id}")
        return run_id


@activity.defn
async def poll_training_run(params: dict) -> dict:
    """
    Poll GET /rl/runs/{run_id} until status is completed/failed
    or timeout_s is exceeded.
    """
    run_id: str    = params["run_id"]
    timeout_s: int = params.get("timeout_s", 21600)
    poll_interval  = 30  # seconds

    deadline = time.monotonic() + timeout_s
    headers = await _auth_headers()
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, headers=headers) as client:
        while time.monotonic() < deadline:
            resp = await client.get(f"{RL_TRAIN_URL}/rl/runs/{run_id}")
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
        "startDate":      params["start_date"],
        "endDate":        params["end_date"],
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
    """
    Resolve the policy_bundle for run_id, then POST /rl/policies/{policy_id}/promote.
    Requires run_id in params.
    """
    run_id: str = params["run_id"]
    headers = await _auth_headers()
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, headers=headers) as client:
        # Resolve policy_id: list all policies and match on training_run_id
        resp = await client.get(f"{RL_TRAIN_URL}/rl/policies")
        resp.raise_for_status()
        policies = resp.json()
        matching = [p for p in policies if str(p.get("training_run_id")) == str(run_id)]
        if not matching:
            raise RuntimeError(f"No policy_bundle found for run_id={run_id}")
        policy_id = matching[0]["id"]

        resp = await client.post(f"{RL_TRAIN_URL}/rl/policies/{policy_id}/promote")
        resp.raise_for_status()
        data = resp.json()
        log.info(f"[promote_policy] run_id={run_id} policy_id={policy_id} promoted={data}")
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
