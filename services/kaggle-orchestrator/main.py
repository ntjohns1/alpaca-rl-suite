"""
Kaggle Orchestrator Service
Manages Kaggle training job lifecycle:
- Exports datasets from PostgreSQL to Kaggle
- Triggers Kaggle notebook runs via API
- Monitors training progress
- Downloads trained models back to MinIO
"""
import os
import io
import json
import logging
import hashlib
import zipfile
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional

import pandas as pd
import psycopg2
import boto3
import requests
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Environment variables
DATABASE_URL = os.environ["DATABASE_URL"]
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://minio:9000")
S3_BUCKET = os.getenv("S3_BUCKET", "alpaca-rl-artifacts")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "minioadmin")
KAGGLE_API_TOKEN = os.getenv("KAGGLE_API_TOKEN", "")
KAGGLE_USERNAME = os.getenv("KAGGLE_USERNAME", "")
KAGGLE_ORCHESTRATOR_PORT = int(os.getenv("KAGGLE_ORCHESTRATOR_PORT", "8011"))

# Configure Kaggle CLI to use the API token
# The Kaggle CLI expects KAGGLE_KEY environment variable
if KAGGLE_API_TOKEN:
    os.environ["KAGGLE_KEY"] = KAGGLE_API_TOKEN
if KAGGLE_USERNAME:
    os.environ["KAGGLE_USERNAME"] = KAGGLE_USERNAME

# Kaggle API base URL
KAGGLE_API_BASE = "https://www.kaggle.com/api/v1"


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
    """Make authenticated request to Kaggle API using API Token (>= 1.8.0)"""
    if not KAGGLE_API_TOKEN:
        raise ValueError("KAGGLE_API_TOKEN must be set")
    
    url = f"{KAGGLE_API_BASE}{endpoint}"
    headers = kwargs.get("headers", {})
    headers["Authorization"] = f"Bearer {KAGGLE_API_TOKEN}"
    kwargs["headers"] = headers
    
    response = requests.request(method, url, **kwargs)
    
    # Log detailed error information
    if response.status_code >= 400:
        log.error(f"Kaggle API error: {response.status_code} - {response.text}")
        log.error(f"Request URL: {url}")
        log.error(f"Request payload: {kwargs.get('json', {})}")
    
    response.raise_for_status()
    return response.json() if response.content else {}


# ─────────────────────────────────────────
# Dataset Export to Kaggle
# ─────────────────────────────────────────
def export_training_dataset(symbol: str, output_path: str) -> dict:
    """Export bar data from PostgreSQL to CSV for Kaggle upload"""
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
        "path": output_path
    }


def create_kaggle_dataset(symbol: str, csv_path: str, dataset_slug: str) -> dict:
    """Create or update a Kaggle dataset"""
    # Create dataset metadata
    # Kaggle requires both 'id' and 'slug' fields
    metadata = {
        "title": f"Alpaca RL Trading Data - {symbol}",
        "id": f"{KAGGLE_USERNAME}/{dataset_slug}",
        "slug": dataset_slug,
        "licenses": [{"name": "CC0-1.0"}],
        "resources": [{
            "path": os.path.basename(csv_path),
            "description": f"Daily OHLCV data for {symbol}"
        }]
    }
    
    # Create a temporary directory with metadata and data
    import tempfile
    import shutil
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Write metadata
        metadata_path = os.path.join(tmpdir, "dataset-metadata.json")
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)
        
        # Log the metadata being sent
        log.info(f"Creating Kaggle dataset with metadata: {json.dumps(metadata, indent=2)}")
        
        # Copy CSV
        shutil.copy(csv_path, tmpdir)
        
        # Create dataset using Kaggle CLI (via subprocess)
        import subprocess
        try:
            # Try to create new dataset
            result = subprocess.run(
                ["kaggle", "datasets", "create", "-p", tmpdir],
                capture_output=True, text=True, check=False
            )
            
            if result.returncode != 0:
                log.error(f"Kaggle dataset creation failed. stdout: {result.stdout}, stderr: {result.stderr}")
                
                if "already exists" in result.stderr:
                    # Dataset exists, update it
                    result = subprocess.run(
                        ["kaggle", "datasets", "version", "-p", tmpdir, "-m", "Updated data"],
                        capture_output=True, text=True, check=False
                    )
                    if result.returncode != 0:
                        log.error(f"Kaggle dataset version failed. stdout: {result.stdout}, stderr: {result.stderr}")
                        result.check_returncode()
                    log.info(f"Updated Kaggle dataset: {dataset_slug}")
                else:
                    result.check_returncode()
            else:
                log.info(f"Created Kaggle dataset: {dataset_slug}")
            
            return {
                "dataset_slug": dataset_slug,
                "url": f"https://www.kaggle.com/datasets/{KAGGLE_USERNAME}/{dataset_slug}",
                "status": "success"
            }
        except subprocess.CalledProcessError as e:
            log.error(f"Kaggle dataset creation failed: {e.stderr}")
            raise


def trigger_kaggle_kernel(kernel_slug: str, dataset_slug: str) -> dict:
    """
    Note: Automatic kernel triggering via API requires the kernel to exist with a numeric ID.
    For now, we'll return instructions for manual execution.
    
    TODO: Implement kernel push via Kaggle CLI or get kernel ID from slug first.
    """
    log.info(f"Dataset uploaded: {KAGGLE_USERNAME}/{dataset_slug}")
    log.info(f"Manual step required: Go to https://www.kaggle.com/code/{KAGGLE_USERNAME}/{kernel_slug}")
    log.info(f"1. Add dataset: {KAGGLE_USERNAME}/{dataset_slug}")
    log.info(f"2. Enable GPU (Settings → Accelerator → GPU T4 x2)")
    log.info(f"3. Click 'Run All'")
    
    return {
        "status": "manual_trigger_required",
        "dataset_url": f"https://www.kaggle.com/datasets/{KAGGLE_USERNAME}/{dataset_slug}",
        "kernel_url": f"https://www.kaggle.com/code/{KAGGLE_USERNAME}/{kernel_slug}",
        "instructions": [
            f"1. Open https://www.kaggle.com/code/{KAGGLE_USERNAME}/{kernel_slug}",
            f"2. Add dataset: {KAGGLE_USERNAME}/{dataset_slug}",
            "3. Enable GPU in Settings",
            "4. Click 'Run All'"
        ]
    }


# ─────────────────────────────────────────
# Training Job Management
# ─────────────────────────────────────────
def create_kaggle_job(name: str, config: dict) -> str:
    """Create a Kaggle training job record in database"""
    config_hash = hashlib.sha256(
        json.dumps(config, sort_keys=True).encode()
    ).hexdigest()[:12]
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO kaggle_training_job 
                   (name, config_hash, config, status, created_at)
                   VALUES (%s, %s, %s, 'preparing', NOW()) 
                   RETURNING id""",
                (name, config_hash, json.dumps(config)),
            )
            job_id = str(cur.fetchone()[0])
        conn.commit()
    
    return job_id


def update_kaggle_job(job_id: str, status: str, metadata: dict = None, error: str = None):
    """Update Kaggle training job status"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE kaggle_training_job
                   SET status=%s, metadata=%s, error=%s,
                       updated_at=NOW(),
                       completed_at=CASE WHEN %s IN ('completed','failed') THEN NOW() ELSE completed_at END
                   WHERE id=%s""",
                (status, json.dumps(metadata) if metadata else None, error, status, job_id),
            )
        conn.commit()


def download_model_from_kaggle(kernel_slug: str, output_path: str) -> str:
    """Download trained model from Kaggle kernel output"""
    import subprocess
    
    # Download kernel output
    result = subprocess.run(
        ["kaggle", "kernels", "output", f"{KAGGLE_USERNAME}/{kernel_slug}", "-p", output_path],
        capture_output=True, text=True, check=True
    )
    
    log.info(f"Downloaded Kaggle kernel output to {output_path}")
    return output_path


def upload_model_to_minio(local_path: str, s3_key: str) -> str:
    """Upload trained model from Kaggle to MinIO"""
    s3 = get_s3()
    
    with open(local_path, "rb") as f:
        s3.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=f.read())
    
    log.info(f"Uploaded model to MinIO: s3://{S3_BUCKET}/{s3_key}")
    return f"s3://{S3_BUCKET}/{s3_key}"


# ─────────────────────────────────────────
# Background Job Orchestration
# ─────────────────────────────────────────
def orchestrate_kaggle_training(job_id: str, config: dict):
    """
    Complete workflow:
    1. Export dataset from PostgreSQL
    2. Upload to Kaggle
    3. Trigger Kaggle notebook
    4. Monitor progress
    5. Download trained model
    6. Upload to MinIO
    """
    try:
        symbol = config["symbols"][0]
        dataset_slug = config.get("datasetSlug") or f"alpaca-rl-{symbol.lower()}"
        kernel_slug = config.get("kernelSlug") or "alpaca-rl-training"
        
        # Step 1: Export dataset
        update_kaggle_job(job_id, "exporting_dataset")
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as tmp:
            csv_path = tmp.name
        
        export_info = export_training_dataset(symbol, csv_path)
        
        # Step 2: Upload to Kaggle
        update_kaggle_job(job_id, "uploading_dataset", {"export_info": export_info})
        dataset_info = create_kaggle_dataset(symbol, csv_path, dataset_slug)
        
        # Step 3: Trigger Kaggle notebook
        update_kaggle_job(job_id, "triggering_kernel", {"dataset_info": dataset_info})
        kernel_info = trigger_kaggle_kernel(kernel_slug, dataset_slug)
        
        # Step 4: Update job with kernel info
        update_kaggle_job(job_id, "training_on_kaggle", {
            "kernel_info": kernel_info,
            "kaggle_url": f"https://www.kaggle.com/code/{KAGGLE_USERNAME}/{kernel_slug}"
        })
        
        log.info(f"[{job_id}] Kaggle training job initiated successfully")
        log.info(f"Monitor at: https://www.kaggle.com/code/{KAGGLE_USERNAME}/{kernel_slug}")
        
        # Note: Steps 5-6 (download & upload) should be triggered by a separate webhook
        # when the Kaggle notebook completes, or polled periodically
        
    except Exception as e:
        log.error(f"[{job_id}] Kaggle orchestration failed: {e}", exc_info=True)
        update_kaggle_job(job_id, "failed", error=str(e))


def complete_kaggle_training(job_id: str, kernel_slug: str):
    """Download model from Kaggle and upload to MinIO"""
    try:
        update_kaggle_job(job_id, "downloading_model")
        
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # Download from Kaggle
            download_model_from_kaggle(kernel_slug, tmpdir)
            
            # Find model file
            model_files = [f for f in os.listdir(tmpdir) if f.endswith('.zip')]
            if not model_files:
                raise ValueError("No model file found in Kaggle output")
            
            model_path = os.path.join(tmpdir, model_files[0])
            
            # Upload to MinIO
            update_kaggle_job(job_id, "uploading_model")
            s3_key = f"models/kaggle/{job_id}/policy_best.zip"
            s3_path = upload_model_to_minio(model_path, s3_key)
            
            update_kaggle_job(job_id, "completed", {"model_path": s3_path})
            log.info(f"[{job_id}] Kaggle training completed successfully")
            
    except Exception as e:
        log.error(f"[{job_id}] Model download/upload failed: {e}", exc_info=True)
        update_kaggle_job(job_id, "failed", error=str(e))


# ─────────────────────────────────────────
# FastAPI App
# ─────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Kaggle Orchestrator service started")
    # Create kaggle_training_job table if not exists
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kaggle_training_job (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    name TEXT NOT NULL,
                    config_hash TEXT NOT NULL,
                    config JSONB NOT NULL,
                    status TEXT NOT NULL,
                    metadata JSONB,
                    error TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    completed_at TIMESTAMPTZ
                )
            """)
        conn.commit()
    yield


app = FastAPI(title="Kaggle Orchestrator", lifespan=lifespan)


class KaggleTrainingRequest(BaseModel):
    name: str
    symbols: list[str]
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


@app.post("/kaggle/train")
def start_kaggle_training(req: KaggleTrainingRequest, background_tasks: BackgroundTasks):
    """Initiate a Kaggle training job"""
    config = req.model_dump()
    job_id = create_kaggle_job(req.name, config)
    background_tasks.add_task(orchestrate_kaggle_training, job_id, config)
    
    return {
        "jobId": job_id,
        "status": "preparing",
        "name": req.name,
        "message": "Kaggle training job initiated. Check /kaggle/jobs/{jobId} for status."
    }


@app.post("/kaggle/jobs/{job_id}/complete")
def complete_job(job_id: str, kernel_slug: str, background_tasks: BackgroundTasks):
    """Webhook endpoint to complete a Kaggle job (download model)"""
    background_tasks.add_task(complete_kaggle_training, job_id, kernel_slug)
    return {"jobId": job_id, "status": "downloading_model"}


@app.get("/kaggle/jobs")
def list_kaggle_jobs(limit: int = 50):
    """List all Kaggle training jobs"""
    with get_conn() as conn:
        df = pd.read_sql(
            """SELECT id, name, status, config_hash, created_at, completed_at 
               FROM kaggle_training_job 
               ORDER BY created_at DESC LIMIT %s""",
            conn, params=(limit,)
        )
    return df.to_dict("records")


@app.get("/kaggle/jobs/{job_id}")
def get_kaggle_job(job_id: str):
    """Get Kaggle training job details"""
    with get_conn() as conn:
        df = pd.read_sql(
            "SELECT * FROM kaggle_training_job WHERE id=%s",
            conn, params=(job_id,)
        )
    
    if df.empty:
        raise HTTPException(status_code=404, detail="Job not found")
    
    row = df.iloc[0].to_dict()
    for key in ["config", "metadata"]:
        if isinstance(row.get(key), str):
            row[key] = json.loads(row[key])
    
    return row


@app.get("/kaggle/health")
def health():
    """Health check"""
    kaggle_configured = bool(KAGGLE_API_TOKEN)
    return {
        "status": "ok",
        "service": "kaggle-orchestrator",
        "kaggle_configured": kaggle_configured,
        "kaggle_cli_version": "1.8.0+",
        "auth_method": "API Token (Bearer)"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=KAGGLE_ORCHESTRATOR_PORT)
