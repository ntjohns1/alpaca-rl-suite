"""
Kaggle Orchestrator Service
Manages Kaggle training job lifecycle:
- Exports datasets from PostgreSQL to Kaggle
- Triggers Kaggle notebook runs via API
- Polls for training completion
- Downloads trained models back to MinIO
- Manual approval gates before policy promotion
"""
import asyncio
import io
import json
import logging
import hashlib
import os
import shutil
import subprocess
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator, Optional

import boto3
import pandas as pd
import psycopg2
import requests
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────
DATABASE_URL             = os.environ["DATABASE_URL"]
S3_ENDPOINT              = os.getenv("S3_ENDPOINT", "http://minio:9000")
S3_BUCKET                = os.getenv("S3_BUCKET", "alpaca-rl-artifacts")
S3_ACCESS_KEY            = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY            = os.getenv("S3_SECRET_KEY", "minioadmin")
KAGGLE_API_TOKEN         = os.getenv("KAGGLE_API_TOKEN", "")
KAGGLE_USERNAME          = os.getenv("KAGGLE_USERNAME", "")
KAGGLE_ORCHESTRATOR_PORT = int(os.getenv("KAGGLE_ORCHESTRATOR_PORT", "8011"))
KAGGLE_POLL_INTERVAL_S   = int(os.getenv("KAGGLE_POLL_INTERVAL_S", "60"))
BACKTEST_SERVICE_URL     = os.getenv("BACKTEST_SERVICE_URL", "http://backtest:8001")

# Configure Kaggle CLI env vars
if KAGGLE_API_TOKEN:
    os.environ["KAGGLE_KEY"] = KAGGLE_API_TOKEN
if KAGGLE_USERNAME:
    os.environ["KAGGLE_USERNAME"] = KAGGLE_USERNAME

KAGGLE_API_BASE = "https://www.kaggle.com/api/v1"


# ─────────────────────────────────────────
# Infrastructure helpers
# ─────────────────────────────────────────
def get_s3():
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
    )


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def kaggle_request(method: str, endpoint: str, **kwargs):
    """Make authenticated request to Kaggle API using Bearer token."""
    if not KAGGLE_API_TOKEN:
        raise ValueError("KAGGLE_API_TOKEN must be set")
    url = f"{KAGGLE_API_BASE}{endpoint}"
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {KAGGLE_API_TOKEN}"
    response = requests.request(method, url, headers=headers, **kwargs)
    if response.status_code >= 400:
        log.error(f"Kaggle API {response.status_code} @ {url}: {response.text}")
    response.raise_for_status()
    return response.json() if response.content else {}


# ─────────────────────────────────────────
# Dataset Export
# ─────────────────────────────────────────
def export_training_dataset(symbol: str, output_path: str) -> dict:
    """Export bar data from PostgreSQL to CSV for Kaggle upload."""
    with get_conn() as conn:
        df = pd.read_sql(
            """SELECT time::date as date, open::float, high::float,
                      low::float, close::float, volume::bigint
               FROM bar_1d WHERE symbol=%s ORDER BY time""",
            conn, params=(symbol,),
        )
    if len(df) < 300:
        raise ValueError(f"Insufficient data for {symbol}: {len(df)} bars")
    df.to_csv(output_path, index=False)
    log.info(f"Exported {len(df)} bars for {symbol} to {output_path}")
    return {
        "symbol": symbol,
        "rows": len(df),
        "date_range": f"{df['date'].min()} to {df['date'].max()}",
        "path": output_path,
    }


def create_kaggle_dataset(symbol: str, csv_path: str, dataset_slug: str) -> dict:
    """Create or update a Kaggle dataset via CLI."""
    metadata = {
        "title": f"Alpaca RL Trading Data - {symbol}",
        "id": f"{KAGGLE_USERNAME}/{dataset_slug}",
        "slug": dataset_slug,
        "licenses": [{"name": "CC0-1.0"}],
        "resources": [{"path": os.path.basename(csv_path), "description": f"Daily OHLCV for {symbol}"}],
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, "dataset-metadata.json"), "w") as f:
            json.dump(metadata, f, indent=2)
        shutil.copy(csv_path, tmpdir)

        result = subprocess.run(
            ["kaggle", "datasets", "create", "-p", tmpdir],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            if "already exists" in result.stderr:
                result = subprocess.run(
                    ["kaggle", "datasets", "version", "-p", tmpdir, "-m", "Updated data"],
                    capture_output=True, text=True, check=True,
                )
                log.info(f"Updated Kaggle dataset: {dataset_slug}")
            else:
                log.error(f"Dataset create failed: {result.stderr}")
                result.check_returncode()
        else:
            log.info(f"Created Kaggle dataset: {dataset_slug}")

    return {
        "dataset_slug": dataset_slug,
        "url": f"https://www.kaggle.com/datasets/{KAGGLE_USERNAME}/{dataset_slug}",
        "status": "success",
    }


# ─────────────────────────────────────────
# Kernel triggering & polling
# ─────────────────────────────────────────
def push_kaggle_kernel(kernel_slug: str, dataset_slug: str) -> dict:
    """Push kernel via CLI to trigger execution."""
    kernel_dir = os.path.join(tempfile.gettempdir(), f"kernel_{kernel_slug}")
    os.makedirs(kernel_dir, exist_ok=True)

    kernel_meta = {
        "id": f"{KAGGLE_USERNAME}/{kernel_slug}",
        "title": "Alpaca RL Training",
        "code_file": "alpaca-rl-training.ipynb",
        "language": "python",
        "kernel_type": "notebook",
        "is_private": True,
        "enable_gpu": True,
        "enable_internet": False,
        "dataset_sources": [f"{KAGGLE_USERNAME}/{dataset_slug}"],
        "competition_sources": [],
        "kernel_sources": [],
    }
    with open(os.path.join(kernel_dir, "kernel-metadata.json"), "w") as f:
        json.dump(kernel_meta, f, indent=2)

    result = subprocess.run(
        ["kaggle", "kernels", "push", "-p", kernel_dir],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        log.warning(f"Kernel push warning: {result.stderr}")

    return {
        "status": "triggered",
        "kernel_url": f"https://www.kaggle.com/code/{KAGGLE_USERNAME}/{kernel_slug}",
        "stdout": result.stdout,
    }


def get_kernel_status(kernel_slug: str) -> str:
    """Poll Kaggle for kernel run status. Returns: running|complete|error|cancelAcknowledged"""
    try:
        data = kaggle_request("GET", f"/kernels/{KAGGLE_USERNAME}/{kernel_slug}")
        return data.get("currentRunningVersion", {}).get("status", "unknown")
    except Exception as e:
        log.warning(f"Kernel status poll failed: {e}")
        return "unknown"


# ─────────────────────────────────────────
# Model download & upload
# ─────────────────────────────────────────
def download_model_from_kaggle(kernel_slug: str, output_dir: str) -> str:
    """Download trained model from Kaggle kernel output."""
    subprocess.run(
        ["kaggle", "kernels", "output", f"{KAGGLE_USERNAME}/{kernel_slug}", "-p", output_dir],
        capture_output=True, text=True, check=True,
    )
    log.info(f"Downloaded Kaggle kernel output to {output_dir}")
    return output_dir


def upload_model_to_minio(local_path: str, s3_key: str) -> str:
    """Upload trained model to MinIO."""
    with open(local_path, "rb") as f:
        get_s3().put_object(Bucket=S3_BUCKET, Key=s3_key, Body=f.read())
    log.info(f"Uploaded model to s3://{S3_BUCKET}/{s3_key}")
    return f"s3://{S3_BUCKET}/{s3_key}"


# ─────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────
def create_kaggle_job(name: str, config: dict) -> str:
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:12]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO kaggle_training_job
                   (name, config_hash, config, status, approval_status, created_at)
                   VALUES (%s, %s, %s, 'preparing', 'pending', NOW())
                   RETURNING id""",
                (name, config_hash, json.dumps(config)),
            )
            job_id = str(cur.fetchone()[0])
        conn.commit()
    return job_id


def update_kaggle_job(job_id: str, status: str, metadata: dict = None, error: str = None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE kaggle_training_job
                   SET status=%s, metadata=%s, error=%s, updated_at=NOW(),
                       completed_at=CASE WHEN %s IN ('completed','failed','cancelled') THEN NOW() ELSE completed_at END
                   WHERE id=%s""",
                (status, json.dumps(metadata) if metadata else None, error, status, job_id),
            )
        conn.commit()


def get_job_row(job_id: str) -> dict:
    with get_conn() as conn:
        df = pd.read_sql("SELECT * FROM kaggle_training_job WHERE id=%s", conn, params=(job_id,))
    if df.empty:
        raise HTTPException(status_code=404, detail="Job not found")
    row = df.iloc[0].to_dict()
    for key in ("config", "metadata"):
        if isinstance(row.get(key), str):
            row[key] = json.loads(row[key])
    return row


def trigger_backtest_for_job(job_id: str, policy_id: str, symbol: str):
    """Fire-and-forget: ask backtest service to run on the newly downloaded model."""
    try:
        payload = {
            "name": f"auto-backtest-{job_id[:8]}",
            "symbols": [symbol],
            "startDate": "2024-01-01",
            "endDate": "2024-12-31",
            "policyId": policy_id,
        }
        resp = requests.post(f"{BACKTEST_SERVICE_URL}/backtest/run", json=payload, timeout=10)
        resp.raise_for_status()
        log.info(f"[{job_id}] Auto-backtest triggered: {resp.json().get('reportId')}")
    except Exception as e:
        log.warning(f"[{job_id}] Auto-backtest trigger failed: {e}")


# ─────────────────────────────────────────
# Orchestration workflow
# ─────────────────────────────────────────
def orchestrate_kaggle_training(job_id: str, config: dict):
    """
    Full automated workflow (runs in a background thread):
    1. Export dataset
    2. Upload to Kaggle datasets
    3. Push kernel (triggers execution)
    4. Poll until complete
    5. Download model → MinIO
    6. Trigger backtest
    7. Wait for manual approval before promotion
    """
    try:
        symbol       = config["symbols"][0]
        dataset_slug = config.get("datasetSlug") or f"alpaca-rl-{symbol.lower()}"
        kernel_slug  = config.get("kernelSlug") or "alpaca-rl-training"

        # 1. Export dataset
        update_kaggle_job(job_id, "exporting_dataset")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tmp:
            csv_path = tmp.name
        export_info = export_training_dataset(symbol, csv_path)

        # 2. Upload to Kaggle
        update_kaggle_job(job_id, "uploading_dataset", {"export_info": export_info})
        dataset_info = create_kaggle_dataset(symbol, csv_path, dataset_slug)
        os.unlink(csv_path)

        # 3. Push kernel
        update_kaggle_job(job_id, "triggering_kernel", {"dataset_info": dataset_info})
        kernel_info = push_kaggle_kernel(kernel_slug, dataset_slug)
        update_kaggle_job(job_id, "training_on_kaggle", {
            "dataset_info": dataset_info,
            "kernel_info": kernel_info,
            "kaggle_url": kernel_info["kernel_url"],
        })
        log.info(f"[{job_id}] Training started on Kaggle: {kernel_info['kernel_url']}")

        # 4. Poll for completion
        import time
        max_polls = int(os.getenv("KAGGLE_MAX_POLLS", "120"))  # 2h at 60s interval
        for _ in range(max_polls):
            # Check if job was cancelled
            row = get_job_row(job_id)
            if row["status"] == "cancelled":
                log.info(f"[{job_id}] Job cancelled by user")
                return

            k_status = get_kernel_status(kernel_slug)
            log.info(f"[{job_id}] Kaggle kernel status: {k_status}")
            if k_status in ("complete",):
                break
            if k_status in ("error", "cancelAcknowledged"):
                raise RuntimeError(f"Kaggle kernel finished with status: {k_status}")
            time.sleep(KAGGLE_POLL_INTERVAL_S)
        else:
            raise TimeoutError("Kaggle kernel did not complete within the polling window")

        # 5. Download model → MinIO
        update_kaggle_job(job_id, "downloading_model")
        with tempfile.TemporaryDirectory() as tmpdir:
            download_model_from_kaggle(kernel_slug, tmpdir)
            model_files = [f for f in os.listdir(tmpdir) if f.endswith(".zip")]
            if not model_files:
                raise ValueError("No model .zip found in Kaggle output")
            model_path = os.path.join(tmpdir, model_files[0])

            update_kaggle_job(job_id, "uploading_model")
            s3_key   = f"models/kaggle/{job_id}/policy_best.zip"
            s3_path  = upload_model_to_minio(model_path, s3_key)

        # 6. Register policy in DB (unpromoted — awaits approval)
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Insert a policy_bundle row linked to the kaggle job
                # training_run_id is NULL for Kaggle-sourced jobs
                cur.execute(
                    """INSERT INTO policy_bundle
                       (training_run_id, name, version, s3_path, config, metrics,
                        promoted, approval_status)
                       VALUES (NULL, %s, '1.0', %s, %s, '{}', FALSE, 'pending')
                       RETURNING id""",
                    (config.get("name", f"kaggle-{job_id[:8]}"), s3_path, json.dumps(config)),
                )
                policy_id = str(cur.fetchone()[0])
            conn.commit()

        update_kaggle_job(job_id, "pending_approval", {
            "model_path": s3_path,
            "policy_id": policy_id,
            "kaggle_url": kernel_info["kernel_url"],
        })

        # 7. Auto-trigger backtest
        trigger_backtest_for_job(job_id, policy_id, symbol)

        log.info(f"[{job_id}] Model ready. Awaiting manual approval. policy_id={policy_id}")

    except Exception as e:
        log.error(f"[{job_id}] Orchestration failed: {e}", exc_info=True)
        update_kaggle_job(job_id, "failed", error=str(e))


def complete_kaggle_training(job_id: str, kernel_slug: str):
    """Webhook-triggered: download model and upload to MinIO."""
    try:
        update_kaggle_job(job_id, "downloading_model")
        with tempfile.TemporaryDirectory() as tmpdir:
            download_model_from_kaggle(kernel_slug, tmpdir)
            model_files = [f for f in os.listdir(tmpdir) if f.endswith(".zip")]
            if not model_files:
                raise ValueError("No model file found in Kaggle output")
            model_path = os.path.join(tmpdir, model_files[0])
            update_kaggle_job(job_id, "uploading_model")
            s3_key  = f"models/kaggle/{job_id}/policy_best.zip"
            s3_path = upload_model_to_minio(model_path, s3_key)
            update_kaggle_job(job_id, "pending_approval", {"model_path": s3_path})
            log.info(f"[{job_id}] Model uploaded. Awaiting approval.")
    except Exception as e:
        log.error(f"[{job_id}] Download/upload failed: {e}", exc_info=True)
        update_kaggle_job(job_id, "failed", error=str(e))


# ─────────────────────────────────────────
# FastAPI App
# ─────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Kaggle Orchestrator service started")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kaggle_training_job (
                    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
                    name            TEXT        NOT NULL,
                    config_hash     TEXT        NOT NULL,
                    config          JSONB       NOT NULL,
                    status          TEXT        NOT NULL DEFAULT 'preparing',
                    approval_status TEXT        NOT NULL DEFAULT 'pending',
                    approved_by     TEXT,
                    approved_at     TIMESTAMPTZ,
                    rejection_reason TEXT,
                    metadata        JSONB,
                    error           TEXT,
                    created_at      TIMESTAMPTZ DEFAULT NOW(),
                    updated_at      TIMESTAMPTZ DEFAULT NOW(),
                    completed_at    TIMESTAMPTZ
                )
            """)
            # Apply migration columns idempotently
            for col, defn in [
                ("approval_status", "TEXT NOT NULL DEFAULT 'pending'"),
                ("approved_by",     "TEXT"),
                ("approved_at",     "TIMESTAMPTZ"),
                ("rejection_reason","TEXT"),
            ]:
                cur.execute(f"""
                    DO $$ BEGIN
                        ALTER TABLE kaggle_training_job ADD COLUMN IF NOT EXISTS {col} {defn};
                    EXCEPTION WHEN duplicate_column THEN NULL;
                    END $$;
                """)
        conn.commit()
    yield


app = FastAPI(title="Kaggle Orchestrator")


# ─────────────────────────────────────────
# Request / Response Models
# ─────────────────────────────────────────
class KaggleTrainingRequest(BaseModel):
    name: str
    symbols: list[str] = Field(..., min_length=1)
    datasetSlug: Optional[str] = None
    kernelSlug: str = "alpaca-rl-training"
    totalTimesteps: int = 500_000
    tradingDays: int = 252
    tradingCostBps: float = 10
    timeCostBps: float = 1
    gamma: float = 0.99
    learningRate: float = 1e-4
    batchSize: int = 256
    architecture: list[int] = Field(default=[256, 256])


class ApprovalRequest(BaseModel):
    approved_by: Optional[str] = "admin"


class RejectionRequest(BaseModel):
    reason: Optional[str] = None
    rejected_by: Optional[str] = "admin"


# ─────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────
@app.post("/kaggle/train", status_code=201)
def start_kaggle_training(req: KaggleTrainingRequest, background_tasks: BackgroundTasks):
    """Initiate a Kaggle training job (full automated workflow)."""
    config = req.model_dump()
    job_id = create_kaggle_job(req.name, config)
    background_tasks.add_task(orchestrate_kaggle_training, job_id, config)
    return {
        "jobId": job_id,
        "status": "preparing",
        "name": req.name,
        "message": f"Job initiated. Poll /kaggle/jobs/{job_id} or stream /kaggle/jobs/{job_id}/stream.",
    }


@app.get("/kaggle/jobs")
def list_kaggle_jobs(
    status: Optional[str] = None,
    approval_status: Optional[str] = None,
    limit: int = 50,
):
    """List Kaggle training jobs with optional filters."""
    conditions = []
    params: list = []
    if status:
        conditions.append("status = %s")
        params.append(status)
    if approval_status:
        conditions.append("approval_status = %s")
        params.append(approval_status)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)

    with get_conn() as conn:
        df = pd.read_sql(
            f"""SELECT id, name, status, approval_status, config_hash,
                       created_at, updated_at, completed_at
               FROM kaggle_training_job {where}
               ORDER BY created_at DESC LIMIT %s""",
            conn, params=params,
        )
    return df.to_dict("records")


@app.get("/kaggle/jobs/{job_id}")
def get_kaggle_job(job_id: str):
    """Get full Kaggle job details."""
    return get_job_row(job_id)


@app.get("/kaggle/jobs/{job_id}/stream")
async def stream_job_status(job_id: str, request: Request):
    """
    Server-Sent Events stream for real-time job status updates.
    The client receives status changes as 'data: {json}' events.
    """
    async def event_generator() -> AsyncGenerator[str, None]:
        last_status = None
        for _ in range(300):  # max ~5 min at 1s interval
            if await request.is_disconnected():
                break
            try:
                row = get_job_row(job_id)
                current_status = row["status"]
                if current_status != last_status:
                    last_status = current_status
                    payload = json.dumps({
                        "jobId":          job_id,
                        "status":         current_status,
                        "approvalStatus": row.get("approval_status"),
                        "metadata":       row.get("metadata"),
                        "error":          row.get("error"),
                        "updatedAt":      str(row.get("updated_at", "")),
                    })
                    yield f"data: {payload}\n\n"
                if current_status in ("completed", "failed", "cancelled", "pending_approval"):
                    break
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                break
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/kaggle/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    """Cancel a running or pending Kaggle job."""
    row = get_job_row(job_id)
    if row["status"] in ("completed", "failed", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Job already in terminal state: {row['status']}")
    update_kaggle_job(job_id, "cancelled")
    return {"jobId": job_id, "status": "cancelled"}


@app.post("/kaggle/jobs/{job_id}/complete")
def complete_job(job_id: str, kernel_slug: str, background_tasks: BackgroundTasks):
    """Webhook: trigger model download from completed Kaggle kernel."""
    background_tasks.add_task(complete_kaggle_training, job_id, kernel_slug)
    return {"jobId": job_id, "status": "downloading_model"}


@app.post("/kaggle/jobs/{job_id}/approve-promotion")
def approve_job_promotion(job_id: str, req: ApprovalRequest):
    """
    Approve a completed job for policy promotion.
    The job must be in 'pending_approval' status.
    """
    row = get_job_row(job_id)
    if row["status"] != "pending_approval":
        raise HTTPException(
            status_code=400,
            detail=f"Job must be in 'pending_approval' state (current: {row['status']})",
        )
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE kaggle_training_job
                   SET approval_status='approved', approved_by=%s,
                       approved_at=NOW(), updated_at=NOW()
                   WHERE id=%s""",
                (req.approved_by, job_id),
            )
            # Also promote the associated policy_bundle
            policy_id = (row.get("metadata") or {}).get("policy_id")
            if policy_id:
                cur.execute(
                    """UPDATE policy_bundle
                       SET promoted=TRUE, promoted_at=NOW(), promoted_by=%s,
                           approval_status='approved', approved_by=%s, approved_at=NOW()
                       WHERE id=%s""",
                    (req.approved_by, req.approved_by, policy_id),
                )
        conn.commit()
    log.info(f"[{job_id}] Approved for promotion by {req.approved_by}")
    return {
        "jobId":          job_id,
        "approvalStatus": "approved",
        "approvedBy":     req.approved_by,
        "policyId":       (row.get("metadata") or {}).get("policy_id"),
    }


@app.post("/kaggle/jobs/{job_id}/reject-promotion")
def reject_job_promotion(job_id: str, req: RejectionRequest):
    """
    Reject a job from promotion. The model is archived but not deleted.
    """
    row = get_job_row(job_id)
    if row["status"] not in ("pending_approval", "completed"):
        raise HTTPException(
            status_code=400,
            detail=f"Job must be in 'pending_approval' or 'completed' state (current: {row['status']})",
        )
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE kaggle_training_job
                   SET approval_status='rejected', rejection_reason=%s,
                       updated_at=NOW()
                   WHERE id=%s""",
                (req.reason, job_id),
            )
            policy_id = (row.get("metadata") or {}).get("policy_id")
            if policy_id:
                cur.execute(
                    """UPDATE policy_bundle
                       SET approval_status='rejected', rejection_reason=%s
                       WHERE id=%s""",
                    (req.reason, policy_id),
                )
        conn.commit()
    log.info(f"[{job_id}] Rejected: {req.reason}")
    return {"jobId": job_id, "approvalStatus": "rejected", "reason": req.reason}


@app.get("/kaggle/quota")
def get_kaggle_quota():
    """Retrieve GPU quota information from Kaggle API."""
    try:
        data = kaggle_request("GET", "/users/me")
        return {
            "username":    data.get("userName"),
            "gpuQuota":    data.get("gpuQuotaUser"),
            "gpuUsed":     data.get("gpuQuotaUsed"),
            "gpuRemaining": (data.get("gpuQuotaUser", 0) - data.get("gpuQuotaUsed", 0)),
            "kaggle_url":  "https://www.kaggle.com/settings",
        }
    except Exception as e:
        return {"error": str(e), "message": "Check https://www.kaggle.com/settings for quota"}


@app.get("/kaggle/health")
def health():
    return {
        "status":           "ok",
        "service":          "kaggle-orchestrator",
        "kaggle_configured": bool(KAGGLE_API_TOKEN),
        "auth_method":      "API Token (Bearer)",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=KAGGLE_ORCHESTRATOR_PORT)
