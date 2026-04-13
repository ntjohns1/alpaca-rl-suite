"""
Dashboard Service
Aggregates system health and activity across all alpaca-rl-suite services.
Provides a unified view for the web UI.
"""
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime

import pandas as pd
import psycopg2
import requests
from fastapi import FastAPI, Query

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────
DATABASE_URL        = os.environ["DATABASE_URL"]
DASHBOARD_PORT      = int(os.getenv("DASHBOARD_PORT", "8020"))
KAGGLE_SERVICE_URL  = os.getenv("KAGGLE_SERVICE_URL",  "http://kaggle-orchestrator:8011")
BACKTEST_SERVICE_URL = os.getenv("BACKTEST_SERVICE_URL", "http://backtest:8001")
RL_TRAIN_SERVICE_URL = os.getenv("RL_TRAIN_SERVICE_URL", "http://rl-train:8004")
DATASET_SERVICE_URL  = os.getenv("DATASET_SERVICE_URL",  "http://dataset-builder:8003")

SERVICE_REGISTRY = {
    "kaggle-orchestrator": f"{KAGGLE_SERVICE_URL}/kaggle/health",
    "backtest":            f"{BACKTEST_SERVICE_URL}/backtest/health",
    "rl-train":            f"{RL_TRAIN_SERVICE_URL}/rl/train/health",
    "dataset-builder":     f"{DATASET_SERVICE_URL}/datasets/health",
}


def get_conn():
    return psycopg2.connect(DATABASE_URL)


# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────
def check_service_health(name: str, url: str) -> dict:
    """Ping a service health endpoint; return status dict."""
    try:
        resp = requests.get(url, timeout=3)
        resp.raise_for_status()
        return {"service": name, "status": "ok", "latencyMs": int(resp.elapsed.total_seconds() * 1000)}
    except requests.exceptions.ConnectionError:
        return {"service": name, "status": "unreachable", "latencyMs": None}
    except requests.exceptions.Timeout:
        return {"service": name, "status": "timeout", "latencyMs": None}
    except Exception as e:
        return {"service": name, "status": "error", "error": str(e), "latencyMs": None}


def get_pending_approvals_count() -> int:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM kaggle_training_job WHERE status = 'pending_approval'"
                )
                return cur.fetchone()[0]
    except Exception:
        return 0


def get_active_jobs_count() -> int:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT COUNT(*) FROM kaggle_training_job
                       WHERE status NOT IN ('completed','failed','cancelled','pending_approval')"""
                )
                return cur.fetchone()[0]
    except Exception:
        return 0


def get_recent_activity(limit: int = 20) -> list[dict]:
    """Aggregate recent events from training jobs and backtest reports."""
    events = []

    try:
        with get_conn() as conn:
            # Recent Kaggle jobs
            df = pd.read_sql(
                """SELECT id, name, status, approval_status, created_at, updated_at
                   FROM kaggle_training_job
                   ORDER BY updated_at DESC LIMIT %s""",
                conn, params=(limit,),
            )
            for _, row in df.iterrows():
                events.append({
                    "type":      "training_job",
                    "id":        str(row["id"]),
                    "name":      row["name"],
                    "status":    row["status"],
                    "subStatus": row.get("approval_status"),
                    "timestamp": str(row["updated_at"]),
                })

            # Recent backtests
            df2 = pd.read_sql(
                """SELECT id, name, status, created_at
                   FROM backtest_report
                   ORDER BY created_at DESC LIMIT %s""",
                conn, params=(limit,),
            )
            for _, row in df2.iterrows():
                events.append({
                    "type":      "backtest",
                    "id":        str(row["id"]),
                    "name":      row["name"],
                    "status":    row["status"],
                    "subStatus": None,
                    "timestamp": str(row["created_at"]),
                })
    except Exception as e:
        log.warning(f"Activity fetch failed: {e}")

    events.sort(key=lambda x: x["timestamp"], reverse=True)
    return events[:limit]


def get_system_stats() -> dict:
    """Aggregate high-level system statistics from the database."""
    stats = {
        "totalTrainingJobs":    0,
        "completedJobs":        0,
        "failedJobs":           0,
        "pendingApprovals":     0,
        "promotedPolicies":     0,
        "totalBacktests":       0,
        "completedBacktests":   0,
        "totalDatasets":        0,
    }
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT status, COUNT(*) FROM kaggle_training_job GROUP BY status")
                for status, count in cur.fetchall():
                    stats["totalTrainingJobs"] += count
                    if status == "pending_approval":
                        stats["pendingApprovals"] = count
                    elif status == "completed":
                        stats["completedJobs"] = count
                    elif status == "failed":
                        stats["failedJobs"] = count

                cur.execute("SELECT COUNT(*) FROM policy_bundle WHERE promoted = TRUE")
                stats["promotedPolicies"] = cur.fetchone()[0]

                cur.execute("SELECT status, COUNT(*) FROM backtest_report GROUP BY status")
                for status, count in cur.fetchall():
                    stats["totalBacktests"] += count
                    if status == "completed":
                        stats["completedBacktests"] = count

                cur.execute("SELECT COUNT(*) FROM dataset_manifest")
                stats["totalDatasets"] = cur.fetchone()[0]
    except Exception as e:
        log.warning(f"Stats fetch failed: {e}")

    return stats


# ─────────────────────────────────────────
# FastAPI App
# ─────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Dashboard service started")
    yield


app = FastAPI(title="Dashboard Service", lifespan=lifespan)


@app.get("/dashboard/overview")
def get_overview():
    """System overview: health of all services + aggregated stats."""
    service_statuses = [
        check_service_health(name, url) for name, url in SERVICE_REGISTRY.items()
    ]
    all_ok = all(s["status"] == "ok" for s in service_statuses)

    return {
        "systemStatus":     "healthy" if all_ok else "degraded",
        "checkedAt":        datetime.utcnow().isoformat(),
        "services":         service_statuses,
        "stats":            get_system_stats(),
        "pendingApprovals": get_pending_approvals_count(),
        "activeJobs":       get_active_jobs_count(),
    }


@app.get("/dashboard/services")
def get_services():
    """Health status for each registered service."""
    return {
        "services":  [check_service_health(name, url) for name, url in SERVICE_REGISTRY.items()],
        "checkedAt": datetime.utcnow().isoformat(),
    }


@app.get("/dashboard/activity")
def get_activity(limit: int = Query(default=20, ge=1, le=100)):
    """Recent activity feed (training jobs + backtests)."""
    return {
        "events":      get_recent_activity(limit),
        "generatedAt": datetime.utcnow().isoformat(),
    }


@app.get("/dashboard/health")
def health():
    return {"status": "ok", "service": "dashboard"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=DASHBOARD_PORT)
