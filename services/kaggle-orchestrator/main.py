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
import json
import logging
import hashlib
import os
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

import boto3
import pandas as pd
import psycopg2
import requests
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from requests.auth import HTTPBasicAuth

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))
from keycloak_auth import keycloak_auth_from_env, make_auth_dependencies  # noqa: E402

_keycloak_auth = keycloak_auth_from_env()
get_current_user, _, _ = make_auth_dependencies(_keycloak_auth)


def _username(user: dict) -> str:
    return user.get("preferred_username") or user.get("email") or user.get("sub") or "unknown"

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

KAGGLE_API_BASE = "https://www.kaggle.com/api/v1"
KAGGLE_BLOB_API_BASE = "https://api.kaggle.com/v1"

# In Docker the notebook is at /kaggle/notebooks/; locally it's two levels up.
_LOCAL_NOTEBOOK = os.path.join(
    os.path.dirname(__file__), "..", "..", "kaggle", "notebooks", "alpaca-rl-training.ipynb"
)
_DOCKER_NOTEBOOK = "/kaggle/notebooks/alpaca-rl-training.ipynb"
NOTEBOOK_PATH = _LOCAL_NOTEBOOK if os.path.isfile(_LOCAL_NOTEBOOK) else _DOCKER_NOTEBOOK


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


def _kaggle_auth() -> HTTPBasicAuth:
    if not KAGGLE_USERNAME or not KAGGLE_API_TOKEN:
        raise ValueError("KAGGLE_USERNAME and KAGGLE_API_TOKEN must be set")
    return HTTPBasicAuth(KAGGLE_USERNAME, KAGGLE_API_TOKEN)


KAGGLE_REQUEST_TIMEOUT = int(os.getenv("KAGGLE_REQUEST_TIMEOUT", "120"))


def kaggle_request(method: str, endpoint: str, **kwargs):
    """Make authenticated request to Kaggle API using HTTP Basic auth."""
    url = f"{KAGGLE_API_BASE}{endpoint}"
    if "auth" not in kwargs:
        kwargs["auth"] = _kaggle_auth()
    kwargs.setdefault("timeout", KAGGLE_REQUEST_TIMEOUT)
    response = requests.request(method, url, **kwargs)
    if response.status_code >= 400:
        log.error("Kaggle API %s @ %s: %s", response.status_code, url, response.text)
    response.raise_for_status()
    return response.json() if response.content else {}


# ─────────────────────────────────────────
# Dataset Export
# ─────────────────────────────────────────
def export_training_dataset(symbol: str, output_path: str) -> dict:
    """Export pre-computed feature rows (20 features + close) to CSV for Kaggle upload."""
    with get_conn() as conn:
        df = pd.read_sql(
            """SELECT f.time::date as date,
                      f.ret_1d, f.ret_2d, f.ret_5d, f.ret_10d, f.ret_21d,
                      f.rsi, f.macd, f.atr, f.stoch, f.ultosc,
                      f.pe, f.pb, f.ps, f.evebitda, f.marketcap_log,
                      f.roe, f.roa, f.debt_equity, f.revenue_growth, f.fcf_yield,
                      b.close::float as close
               FROM feature_row f
               JOIN bar_1d b USING (time, symbol)
               WHERE f.symbol=%s
               ORDER BY f.time""",
            conn, params=(symbol,),
        )
    if len(df) < 300:
        raise ValueError(f"Insufficient data for {symbol}: {len(df)} feature rows")
    df.to_csv(output_path, index=False)
    log.info(f"Exported {len(df)} feature rows for {symbol} to {output_path}")
    return {
        "symbol": symbol,
        "rows": len(df),
        "date_range": f"{df['date'].min()} to {df['date'].max()}",
        "path": output_path,
        "feature_version": "v2",
    }


def _upload_blob(file_path: str, file_name: str) -> str:
    """Upload a file via the Kaggle blob API and return the blob token."""
    file_size = os.path.getsize(file_path)
    auth = _kaggle_auth()

    blob_url = f"{KAGGLE_BLOB_API_BASE}/blobs.BlobApiService/StartBlobUpload"
    start_resp = requests.post(
        blob_url,
        json={"type": "DATASET", "name": file_name, "contentLength": file_size, "contentType": "text/csv"},
        auth=auth,
        timeout=KAGGLE_REQUEST_TIMEOUT,
    )
    if start_resp.status_code >= 400:
        log.error("Blob API %s @ %s: %s", start_resp.status_code, blob_url, start_resp.text)
    start_resp.raise_for_status()
    try:
        blob_info = start_resp.json()
    except ValueError:
        log.error("Blob API returned non-JSON response: %s", start_resp.text[:500])
        raise

    create_url = blob_info.get("createUrl")
    token = blob_info.get("token")
    if not create_url or not token:
        raise ValueError(
            f"Unexpected StartBlobUpload response (missing createUrl or token): {blob_info}"
        )

    with open(file_path, "rb") as f:
        put_resp = requests.put(
            create_url, data=f,
            headers={"Content-Type": "text/csv", "Content-Length": str(file_size)},
            timeout=600,
        )
    put_resp.raise_for_status()

    return token


def create_kaggle_dataset(symbol: str, csv_path: str, dataset_slug: str) -> dict:
    """Create or update a Kaggle dataset via REST API (no CLI)."""
    file_name = os.path.basename(csv_path)
    blob_token = _upload_blob(csv_path, file_name)

    body = {
        "title": f"Alpaca RL Trading Data - {symbol}",
        "slug": dataset_slug,
        "ownerSlug": KAGGLE_USERNAME,
        "licenseName": "CC0-1.0",
        "isPrivate": True,
        "files": [{"token": blob_token, "description": f"Daily features for {symbol}"}],
    }

    try:
        kaggle_request("POST", "/datasets/create/new", json=body)
        log.info("Created Kaggle dataset: %s", dataset_slug)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 409:
            version_body = {
                "convertToBigQuery": False,
                "deleteOldVersions": False,
                "versionNotes": "Updated data",
                "files": [{"token": blob_token, "description": f"Daily features for {symbol}"}],
            }
            kaggle_request(
                "POST",
                f"/datasets/create/version/{KAGGLE_USERNAME}/{dataset_slug}",
                json=version_body,
            )
            log.info("Updated Kaggle dataset: %s", dataset_slug)
        else:
            raise

    return {
        "dataset_slug": dataset_slug,
        "url": f"https://www.kaggle.com/datasets/{KAGGLE_USERNAME}/{dataset_slug}",
        "status": "success",
    }


# ─────────────────────────────────────────
# Kernel triggering & polling
# ─────────────────────────────────────────
def _get_kernel_id(kernel_slug: str) -> int | None:
    """Look up the numeric kernel ID via the /kernels/pull endpoint.

    The /kernels/list endpoint returns id=0 for all kernels, so we use
    /kernels/pull which returns full metadata including the real numeric ID.
    Returns None if the kernel doesn't exist yet.
    """
    try:
        data = kaggle_request(
            "GET", f"/kernels/pull/{KAGGLE_USERNAME}/{kernel_slug}",
        )
        kid = (data.get("metadata") or {}).get("id")
        if kid and kid > 0:
            return kid
        log.warning("Kernel %s pull returned invalid id=%s", kernel_slug, kid)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            log.info("Kernel %s not found (404), will create new", kernel_slug)
        else:
            log.warning("Failed to look up kernel ID for %s: %s", kernel_slug, e)
    except Exception as e:
        log.warning("Failed to look up kernel ID for %s: %s", kernel_slug, e)
    return None


def push_kaggle_kernel(kernel_slug: str, dataset_slug: str) -> dict:
    """Push kernel via REST API to trigger execution, including the bundled notebook source."""
    notebook_file = os.environ.get("KAGGLE_NOTEBOOK_PATH", NOTEBOOK_PATH)
    if not os.path.isfile(notebook_file):
        raise FileNotFoundError(f"Notebook not found: {notebook_file}")
    with open(notebook_file) as f:
        nb = json.load(f)
    # Strip saved cell outputs to avoid bloating the push payload
    for cell in nb.get("cells", []):
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
    notebook_source = json.dumps(nb)

    body = {
        "title": "Alpaca RL Training",
        "text": notebook_source,
        "language": "python",
        "kernelType": "notebook",
        "isPrivate": True,
        "enableGpu": True,
        "enableInternet": False,
        "datasetDataSources": [f"{KAGGLE_USERNAME}/{dataset_slug}"],
        "competitionDataSources": [],
        "kernelDataSources": [],
        "categoryIds": [],
    }

    # The Kaggle API expects a numeric integer ID for existing kernels.
    # If the kernel doesn't exist yet, we create a new one via newTitle + slug.
    kernel_id = _get_kernel_id(kernel_slug)
    if kernel_id is not None:
        body["id"] = kernel_id
        log.info("Pushing to existing kernel ID %d (%s)", kernel_id, kernel_slug)
    else:
        body["newTitle"] = "Alpaca RL Training"
        body["slug"] = kernel_slug
        log.info("Creating new kernel: %s", kernel_slug)

    resp = kaggle_request("POST", "/kernels/push", json=body)
    log.info("Kernel push response: %s", resp)

    # Check for API-level errors (e.g. missing title, invalid ID)
    if resp.get("hasError") or resp.get("error"):
        raise RuntimeError(f"Kaggle kernels/push failed: {resp.get('error', resp.get('errorNullable', 'unknown'))}")

    return {
        "status": "triggered",
        "kernel_url": f"https://www.kaggle.com/code/{KAGGLE_USERNAME}/{kernel_slug}",
        "version_number": resp.get("versionNumber"),
    }


def get_kernel_status(kernel_slug: str) -> str:
    """Poll Kaggle for kernel run status. Returns: running|complete|error|cancelAcknowledged"""
    try:
        data = kaggle_request("GET", f"/kernels/{KAGGLE_USERNAME}/{kernel_slug}")
        return (data.get("currentRunningVersion") or {}).get("status", "unknown")
    except Exception as e:
        log.warning("Kernel status poll failed: %s", e)
        return "unknown"


# ─────────────────────────────────────────
# Model download & upload
# ─────────────────────────────────────────
def download_model_from_kaggle(kernel_slug: str, output_dir: str) -> str:
    """Download trained model from Kaggle kernel output via REST API."""
    data = kaggle_request(
        "GET", "/kernels/output",
        params={"userName": KAGGLE_USERNAME, "kernelSlug": kernel_slug},
    )

    files = data.get("files", [])
    if not files:
        raise ValueError(f"No output files returned for kernel {kernel_slug}")

    os.makedirs(output_dir, exist_ok=True)
    downloaded = 0
    for file_info in files:
        file_url = file_info.get("url")
        raw_name = file_info.get("fileName", file_info.get("name", "output"))
        file_name = os.path.basename(raw_name)  # sanitize: prevent path traversal
        if not file_name:
            log.warning("Skipping file with empty name: %s", file_info)
            continue
        if not file_url:
            log.warning("Skipping file with no URL: %s", file_info)
            continue
        log.info("Downloading kernel output file: %s", file_name)
        # Don't send Kaggle credentials to third-party download URLs (e.g. GCS)
        dl_resp = requests.get(file_url, stream=True, timeout=600)
        dl_resp.raise_for_status()
        dest = os.path.join(output_dir, file_name)
        with open(dest, "wb") as f:
            for chunk in dl_resp.iter_content(chunk_size=8192):
                f.write(chunk)
        downloaded += 1

    if downloaded == 0:
        raise ValueError(
            f"All {len(files)} output file(s) for kernel {kernel_slug} lacked download URLs"
        )
    log.info("Downloaded %d file(s) from Kaggle kernel output to %s", downloaded, output_dir)
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
                   SET status=%s,
                       metadata=COALESCE(%s, metadata),
                       error=%s,
                       updated_at=NOW(),
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
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", prefix=f"{symbol.lower()}_features_", delete=False,
        ) as tmp:
            csv_path = tmp.name
        try:
            export_info = export_training_dataset(symbol, csv_path)

            # 2. Upload to Kaggle
            update_kaggle_job(job_id, "uploading_dataset", {"export_info": export_info})
            dataset_info = create_kaggle_dataset(symbol, csv_path, dataset_slug)
        finally:
            try:
                os.unlink(csv_path)
            except OSError:
                pass

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


class RejectionRequest(BaseModel):
    reason: Optional[str] = None


# ─────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────
@app.post("/kaggle/train", status_code=201)
def start_kaggle_training(
    req: KaggleTrainingRequest,
    background_tasks: BackgroundTasks,
    _user: dict = Depends(get_current_user),
):
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
    limit: int = Query(50, ge=1, le=500),
    _user: dict = Depends(get_current_user),
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
def get_kaggle_job(job_id: str, _user: dict = Depends(get_current_user)):
    """Get full Kaggle job details."""
    return get_job_row(job_id)


@app.get("/kaggle/jobs/{job_id}/stream")
async def stream_job_status(
    job_id: str,
    request: Request,
    _user: dict = Depends(get_current_user),
):
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
def cancel_job(job_id: str, _user: dict = Depends(get_current_user)):
    """Cancel a running or pending Kaggle job."""
    row = get_job_row(job_id)
    if row["status"] in ("completed", "failed", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Job already in terminal state: {row['status']}")
    update_kaggle_job(job_id, "cancelled")
    return {"jobId": job_id, "status": "cancelled"}


@app.post("/kaggle/jobs/{job_id}/complete")
def complete_job(
    job_id: str,
    kernel_slug: str,
    background_tasks: BackgroundTasks,
    _user: dict = Depends(get_current_user),
):
    """Trigger model download from completed Kaggle kernel."""
    background_tasks.add_task(complete_kaggle_training, job_id, kernel_slug)
    return {"jobId": job_id, "status": "downloading_model"}


@app.post("/kaggle/jobs/{job_id}/approve-promotion")
def approve_job_promotion(job_id: str, user: dict = Depends(get_current_user)):
    """
    Approve a completed job for policy promotion.
    The job must be in 'pending_approval' status.
    Identity is taken from the validated JWT — clients cannot forge it.
    """
    actor = _username(user)
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
                (actor, job_id),
            )
            policy_id = (row.get("metadata") or {}).get("policy_id")
            if policy_id:
                cur.execute(
                    """UPDATE policy_bundle
                       SET promoted=TRUE, promoted_at=NOW(), promoted_by=%s,
                           approval_status='approved', approved_by=%s, approved_at=NOW()
                       WHERE id=%s""",
                    (actor, actor, policy_id),
                )
        conn.commit()
    log.info("[%s] Approved for promotion by %s", job_id, actor)
    return {
        "jobId":          job_id,
        "approvalStatus": "approved",
        "approvedBy":     actor,
        "policyId":       (row.get("metadata") or {}).get("policy_id"),
    }


@app.post("/kaggle/jobs/{job_id}/reject-promotion")
def reject_job_promotion(
    job_id: str,
    req: RejectionRequest,
    user: dict = Depends(get_current_user),
):
    """
    Reject a job from promotion. The model is archived but not deleted.
    Identity is taken from the validated JWT.
    """
    actor = _username(user)
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
    log.info("[%s] Rejected by %s: %s", job_id, actor, req.reason)
    return {
        "jobId":          job_id,
        "approvalStatus": "rejected",
        "rejectedBy":     actor,
        "reason":         req.reason,
    }


@app.get("/kaggle/quota")
def get_kaggle_quota(_user: dict = Depends(get_current_user)):
    """Return Kaggle quota info.

    The Kaggle REST API does not expose a user-profile or GPU-quota
    endpoint via Basic auth, so we return a link to the settings page
    where the user can check quota manually.
    """
    return {
        "username":     KAGGLE_USERNAME or None,
        "message":      "GPU quota is not available via the Kaggle API. Check the link below.",
        "kaggle_url":   "https://www.kaggle.com/settings",
        "configured":   bool(KAGGLE_API_TOKEN and KAGGLE_USERNAME),
    }


@app.get("/kaggle/health")
def health():
    return {
        "status":           "ok",
        "service":          "kaggle-orchestrator",
        "kaggle_configured": bool(KAGGLE_API_TOKEN and KAGGLE_USERNAME),
        "auth_method":      "HTTP Basic (username:apiKey)",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=KAGGLE_ORCHESTRATOR_PORT)
