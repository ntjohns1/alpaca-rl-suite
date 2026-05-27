"""
Kaggle Orchestrator Service
Manages Kaggle integration for the Alpaca RL Suite:
- Exports feature datasets from PostgreSQL and uploads to Kaggle
- Lists user's Kaggle datasets
- Downloads trained models from Kaggle notebook output to MinIO
- Job tracking, approval gates, and policy promotion
"""
import json
import logging
import hashlib
import os
import shutil
import sys
import tempfile
from contextlib import asynccontextmanager
from typing import Optional

import boto3
import pandas as pd
import psycopg2
import requests
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel
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
KAGGLE_API_TOKEN         = os.getenv("KAGGLE_API_TOKEN", "")  # KGAT_ OAuth token (for kagglehub)
KAGGLE_KEY               = os.getenv("KAGGLE_KEY", "")       # Legacy API key (for REST basic auth)
KAGGLE_USERNAME          = os.getenv("KAGGLE_USERNAME", "")
KAGGLE_ORCHESTRATOR_PORT = int(os.getenv("KAGGLE_ORCHESTRATOR_PORT", "8011"))
BACKTEST_SERVICE_URL     = os.getenv("BACKTEST_SERVICE_URL", "http://backtest:8001")

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


def _kaggle_auth() -> HTTPBasicAuth:
    """Basic auth for legacy Kaggle REST API (uses KAGGLE_KEY, not the KGAT_ OAuth token)."""
    if not KAGGLE_USERNAME or not KAGGLE_KEY:
        raise ValueError("KAGGLE_USERNAME and KAGGLE_KEY must be set")
    return HTTPBasicAuth(KAGGLE_USERNAME, KAGGLE_KEY)


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
def export_training_dataset(symbols: list[str], output_path: str) -> dict:
    """Export pre-computed feature rows (20 features + close) to CSV for Kaggle upload.

    Supports single or multiple symbols. Multi-symbol exports include a 'symbol'
    column so the trading environment can sample episodes across stocks.
    """
    placeholders = ",".join(["%s"] * len(symbols))
    with get_conn() as conn:
        df = pd.read_sql(
            f"""SELECT f.time::date as date,
                       f.symbol,
                       f.ret_1d, f.ret_2d, f.ret_5d, f.ret_10d, f.ret_21d,
                       f.rsi, f.macd, f.atr, f.stoch, f.ultosc,
                       f.pe, f.pb, f.ps, f.evebitda, f.marketcap_log,
                       f.roe, f.roa, f.debt_equity, f.revenue_growth, f.fcf_yield,
                       b.close::float as close
                FROM feature_row f
                JOIN bar_1d b USING (time, symbol)
                WHERE f.symbol IN ({placeholders})
                ORDER BY f.symbol, f.time""",
            conn, params=tuple(symbols),
        )
    if len(df) < 300:
        raise ValueError(
            f"Insufficient data for {symbols}: {len(df)} feature rows (need >= 300)"
        )

    # Per-symbol diagnostics
    per_symbol = {}
    for sym in symbols:
        sym_df = df[df["symbol"] == sym]
        if sym_df.empty:
            log.warning("No data found for symbol %s", sym)
            continue
        per_symbol[sym] = {
            "rows": len(sym_df),
            "date_range": f"{sym_df['date'].min()} to {sym_df['date'].max()}",
        }

    # For single-symbol exports, drop the symbol column for backward compat
    if len(symbols) == 1:
        df = df.drop(columns=["symbol"])

    df.to_csv(output_path, index=False)
    log.info(
        "Exported %d feature rows for %s to %s",
        len(df), symbols, output_path,
    )
    return {
        "symbols": symbols,
        "rows": len(df),
        "per_symbol": per_symbol,
        "date_range": f"{df['date'].min()} to {df['date'].max()}",
        "path": output_path,
        "feature_version": "v2",
    }


# ─────────────────────────────────────────
# Kaggle dataset & model operations (kagglehub)
# ─────────────────────────────────────────
def upload_dataset_to_kaggle(symbols: list[str], csv_path: str, dataset_slug: str) -> dict:
    """Upload a dataset to Kaggle using kagglehub.

    kagglehub.dataset_upload() handles create-or-update automatically.
    The CSV file must be in a directory by itself (kagglehub uploads the dir).
    """
    handle = f"{KAGGLE_USERNAME}/{dataset_slug}"
    label = ",".join(symbols)

    # kagglehub expects a directory, so stage the CSV in a temp dir
    with tempfile.TemporaryDirectory() as staging_dir:
        staged = os.path.join(staging_dir, os.path.basename(csv_path))
        # Copy (not move) so caller's file is preserved
        shutil.copy2(csv_path, staged)

        import kagglehub
        kagglehub.dataset_upload(
            handle,
            staging_dir,
            version_notes=f"Updated {label} features",
        )

    log.info("Uploaded dataset to Kaggle via kagglehub: %s", handle)
    return {
        "dataset_slug": dataset_slug,
        "url": f"https://www.kaggle.com/datasets/{handle}",
        "status": "success",
    }


def list_kaggle_datasets() -> list[dict]:
    """List the authenticated user's Kaggle datasets.

    kagglehub doesn't expose a list API, so we use the REST endpoint
    /datasets/list?group=my which returns datasets owned by the authed user.
    """
    data = kaggle_request("GET", "/datasets/list", params={"group": "my"})
    return [
        {
            "id": ds.get("id"),
            "ref": ds.get("ref"),
            "title": ds.get("title"),
            "slug": (ds.get("ref") or "").split("/")[-1],
            "url": ds.get("url"),
            "totalBytes": ds.get("totalBytes"),
            "lastUpdated": ds.get("lastUpdated"),
            "currentVersionNumber": ds.get("currentVersionNumber"),
            "isPrivate": ds.get("isPrivate"),
            "downloadCount": ds.get("downloadCount"),
        }
        for ds in data
    ]


def download_model_via_kagglehub(kernel_slug: str, output_dir: str) -> str:
    """Download trained model from Kaggle notebook output using kagglehub.

    Uses kagglehub.notebook_output_download() which handles auth and
    caching automatically. We copy the results to output_dir.
    """
    handle = f"{KAGGLE_USERNAME}/{kernel_slug}"
    import kagglehub
    cache_path = kagglehub.notebook_output_download(handle, output_dir=output_dir)
    log.info("Downloaded notebook output via kagglehub to %s", cache_path)
    return cache_path


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
class RejectionRequest(BaseModel):
    reason: Optional[str] = None


class DatasetUploadRequest(BaseModel):
    """Upload a dataset to Kaggle from exported features."""
    symbols: list[str]
    datasetSlug: Optional[str] = None

    # Backward compat: accept 'symbol' as alias for single-stock uploads
    @classmethod
    def __get_validators__(cls):
        yield cls._validate

    @classmethod
    def _validate(cls, v):
        return v


class ModelDownloadRequest(BaseModel):
    """Download model from a Kaggle notebook output."""
    kernelSlug: str = "alpaca-rl-training"


# ─────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────
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


@app.post("/kaggle/jobs/{job_id}/cancel")
def cancel_job(job_id: str, _user: dict = Depends(get_current_user)):
    """Cancel a running or pending Kaggle job."""
    row = get_job_row(job_id)
    if row["status"] in ("completed", "failed", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Job already in terminal state: {row['status']}")
    update_kaggle_job(job_id, "cancelled")
    return {"jobId": job_id, "status": "cancelled"}


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


@app.get("/kaggle/health")
def health():
    return {
        "status":           "ok",
        "service":          "kaggle-orchestrator",
        "kaggle_configured": bool(KAGGLE_API_TOKEN and KAGGLE_KEY and KAGGLE_USERNAME),
        "auth_method":      "kagglehub: OAuth (KAGGLE_API_TOKEN), REST: Basic (KAGGLE_KEY)",
    }


# ─────────────────────────────────────────
# Dataset & model endpoints (kagglehub)
# ─────────────────────────────────────────
@app.get("/kaggle/datasets")
def list_datasets(_user: dict = Depends(get_current_user)):
    """List the authenticated user's datasets on Kaggle."""
    try:
        datasets = list_kaggle_datasets()
        return {"datasets": datasets, "count": len(datasets)}
    except Exception as e:
        log.error("Failed to list Kaggle datasets: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Kaggle API error: {e}")


@app.post("/kaggle/datasets/upload", status_code=201)
def upload_dataset(
    req: DatasetUploadRequest,
    _user: dict = Depends(get_current_user),
):
    """Export features for symbol(s) and upload to Kaggle as a dataset."""
    symbols = [s.upper() for s in req.symbols]
    if len(symbols) == 1:
        default_slug = f"alpaca-rl-{symbols[0].lower()}"
    else:
        default_slug = "alpaca-rl-multi-stock"
    dataset_slug = req.datasetSlug or default_slug

    prefix = "_".join(s.lower() for s in symbols[:3])  # keep filename sane
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", prefix=f"{prefix}_features_", delete=False,
    ) as tmp:
        csv_path = tmp.name

    try:
        export_info = export_training_dataset(symbols, csv_path)
        result = upload_dataset_to_kaggle(symbols, csv_path, dataset_slug)
    finally:
        try:
            os.unlink(csv_path)
        except OSError:
            pass

    return {
        "symbols": symbols,
        "datasetSlug": dataset_slug,
        "exportInfo": export_info,
        "kaggleUrl": result["url"],
        "status": "uploaded",
    }


@app.post("/kaggle/models/download", status_code=201)
def download_model(
    req: ModelDownloadRequest,
    _user: dict = Depends(get_current_user),
):
    """Download model from Kaggle notebook output and upload to MinIO."""
    kernel_slug = req.kernelSlug

    with tempfile.TemporaryDirectory() as tmpdir:
        download_model_via_kagglehub(kernel_slug, tmpdir)

        # Find model files (.zip or .pt)
        model_files = [
            f for f in os.listdir(tmpdir)
            if f.endswith((".zip", ".pt", ".pth", ".onnx"))
        ]
        if not model_files:
            # Fall back to any file
            model_files = [f for f in os.listdir(tmpdir) if os.path.isfile(os.path.join(tmpdir, f))]
        if not model_files:
            raise HTTPException(status_code=404, detail="No model files found in notebook output")

        s3_key = f"models/kaggle/{kernel_slug}/{model_files[0]}"
        model_path = os.path.join(tmpdir, model_files[0])
        s3_path = upload_model_to_minio(model_path, s3_key)

    return {
        "kernelSlug": kernel_slug,
        "modelFile": model_files[0],
        "s3Path": s3_path,
        "status": "uploaded_to_minio",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=KAGGLE_ORCHESTRATOR_PORT)
