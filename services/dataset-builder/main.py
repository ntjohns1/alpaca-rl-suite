import os
import io
import json
import hashlib
import logging
from contextlib import asynccontextmanager
from observability import setup_observability
from datetime import datetime

import pandas as pd
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import boto3
import psycopg2
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from typing import Optional

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

DATABASE_URL   = os.environ["DATABASE_URL"]
S3_ENDPOINT    = os.getenv("S3_ENDPOINT", "http://localhost:9000")
S3_BUCKET      = os.getenv("S3_BUCKET", "alpaca-rl-artifacts")
S3_ACCESS_KEY  = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY  = os.getenv("S3_SECRET_KEY", "minioadmin")
DATASET_BUILDER_PORT = int(os.getenv("DATASET_BUILDER_PORT", "8003"))


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
# Walk-forward split builder
# Strict time splits — no lookahead
# ─────────────────────────────────────────
def build_walk_forward_splits(
    df: pd.DataFrame,
    n_splits: int = 5,
    train_frac: float = 0.7,
) -> list[dict]:
    """
    Creates n_splits walk-forward (expanding window) train/test pairs.
    Each split's test window starts strictly after its train window.
    Returns list of dicts: {split, train_start, train_end, test_start, test_end}
    """
    df = df.sort_values("time")
    dates = df["time"].unique()
    n = len(dates)
    min_train = int(n * train_frac / n_splits)

    splits = []
    for i in range(1, n_splits + 1):
        train_end_idx = int(n * train_frac * i / n_splits)
        test_end_idx  = min(train_end_idx + max(int(n * (1 - train_frac) / n_splits), 30), n - 1)
        splits.append({
            "split": i,
            "train_start": str(dates[0]),
            "train_end":   str(dates[train_end_idx]),
            "test_start":  str(dates[train_end_idx + 1]),
            "test_end":    str(dates[test_end_idx]),
        })
    return splits


def fetch_features(symbols: list[str], start_date: str, end_date: str) -> pd.DataFrame:
    with psycopg2.connect(DATABASE_URL) as conn:
        placeholders = ",".join(["%s"] * len(symbols))
        df = pd.read_sql(
            f"""
            SELECT f.time, f.symbol,
                   f.ret_1d, f.ret_2d, f.ret_5d, f.ret_10d, f.ret_21d,
                   f.rsi, f.macd, f.atr, f.stoch, f.ultosc,
                   b.close::float as close
            FROM feature_row f
            JOIN bar_1d b USING (time, symbol)
            WHERE f.symbol IN ({placeholders})
              AND f.time BETWEEN %s AND %s
            ORDER BY f.symbol, f.time
            """,
            conn,
            params=(*symbols, start_date, end_date),
        )
    return df


def upload_parquet(df: pd.DataFrame, s3_path: str) -> str:
    table = pa.Table.from_pandas(df)
    buf = io.BytesIO()
    pq.write_table(table, buf)
    buf.seek(0)
    s3 = get_s3()
    s3.put_object(Bucket=S3_BUCKET, Key=s3_path, Body=buf.getvalue())
    return s3_path


def register_manifest(
    name: str,
    symbols: list[str],
    start_date: str,
    end_date: str,
    n_splits: int,
    s3_path: str,
    feature_version: str,
    metadata: dict,
) -> str:
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO dataset_manifest
                  (name, symbols, start_date, end_date, n_splits, s3_path, feature_version, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (name, symbols, start_date, end_date, n_splits, s3_path, feature_version,
                 json.dumps(metadata)),
            )
            manifest_id = str(cur.fetchone()[0])
        conn.commit()
    return manifest_id


# ─────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Dataset Builder started")
    yield


app = FastAPI(title="Dataset Builder", lifespan=lifespan)
setup_observability(app, "dataset-builder")


class BuildDatasetRequest(BaseModel):
    name: str
    symbols: list[str]
    start_date: str
    end_date: str
    n_splits: int = 5
    train_frac: float = 0.7
    feature_version: str = "v1"


@app.get("/datasets/health")
def health():
    return {"status": "ok", "service": "dataset-builder"}


@app.post("/datasets/build")
def build_dataset(req: BuildDatasetRequest):
    try:
        log.info(f"Building dataset '{req.name}' for {req.symbols}")
        df = fetch_features(req.symbols, req.start_date, req.end_date)
        if df.empty:
            raise HTTPException(status_code=422, detail="No feature data found for requested range")

        splits = build_walk_forward_splits(df, req.n_splits, req.train_frac)

        # Build config hash for reproducibility
        config = {
            "name": req.name, "symbols": sorted(req.symbols),
            "start_date": req.start_date, "end_date": req.end_date,
            "n_splits": req.n_splits, "train_frac": req.train_frac,
        }
        config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:12]

        # Upload each split as parquet
        split_paths = []
        for split in splits:
            train_df = df[(df["time"] >= split["train_start"]) & (df["time"] <= split["train_end"])]
            test_df  = df[(df["time"] >= split["test_start"])  & (df["time"] <= split["test_end"])]
            s3_prefix = f"datasets/{req.name}/{config_hash}/split_{split['split']}"
            upload_parquet(train_df, f"{s3_prefix}/train.parquet")
            upload_parquet(test_df,  f"{s3_prefix}/test.parquet")
            split_paths.append({**split, "s3_prefix": s3_prefix})

        # Upload manifest JSON
        manifest_data = {**config, "config_hash": config_hash, "splits": split_paths,
                         "created_at": datetime.utcnow().isoformat()}
        manifest_path = f"datasets/{req.name}/{config_hash}/manifest.json"
        s3 = get_s3()
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=manifest_path,
            Body=json.dumps(manifest_data).encode(),
        )

        manifest_id = register_manifest(
            name=req.name, symbols=req.symbols,
            start_date=req.start_date, end_date=req.end_date,
            n_splits=req.n_splits, s3_path=manifest_path,
            feature_version=req.feature_version,
            metadata={"config_hash": config_hash, "splits": split_paths},
        )

        return {
            "datasetId": manifest_id,
            "name": req.name,
            "configHash": config_hash,
            "nRows": len(df),
            "nSplits": len(splits),
            "s3Path": manifest_path,
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Dataset build failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/datasets")
def list_datasets():
    with psycopg2.connect(DATABASE_URL) as conn:
        df = pd.read_sql("SELECT * FROM dataset_manifest ORDER BY created_at DESC", conn)
    return df.to_dict("records")


@app.post("/datasets/export")
def export_dataset(
    symbols: list[str] = Query(...),
    format: str = Query(default="csv", pattern="^(csv|parquet)$"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    """
    Export feature data for given symbols to CSV or Parquet.
    Returns the file as a streaming download.
    """
    try:
        s_date = start_date or "2020-01-01"
        e_date = end_date   or datetime.utcnow().strftime("%Y-%m-%d")
        df = fetch_features(symbols, s_date, e_date)
        if df.empty:
            raise HTTPException(status_code=422, detail="No data found for requested range")

        filename = f"alpaca_rl_{'_'.join(symbols)}_{s_date}_{e_date}"

        if format == "csv":
            buf = io.StringIO()
            df.to_csv(buf, index=False)
            return Response(
                content=buf.getvalue().encode(),
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
            )
        else:  # parquet
            buf = io.BytesIO()
            table = pa.Table.from_pandas(df)
            pq.write_table(table, buf)
            buf.seek(0)
            return Response(
                content=buf.read(),
                media_type="application/octet-stream",
                headers={"Content-Disposition": f'attachment; filename="{filename}.parquet"'},
            )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Export failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/datasets/preview")
def preview_dataset(
    symbols: list[str] = Query(...),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    rows: int = Query(default=20, ge=1, le=200),
):
    """Return a preview of feature data (up to `rows` rows per symbol)."""
    try:
        s_date = start_date or "2020-01-01"
        e_date = end_date   or datetime.utcnow().strftime("%Y-%m-%d")
        df = fetch_features(symbols, s_date, e_date)
        if df.empty:
            raise HTTPException(status_code=422, detail="No data found")
        preview = df.head(rows)
        return {
            "symbols":    symbols,
            "startDate":  s_date,
            "endDate":    e_date,
            "totalRows":  len(df),
            "previewRows": len(preview),
            "columns":    list(df.columns),
            "data":       preview.to_dict("records"),
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Preview failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str):
    with psycopg2.connect(DATABASE_URL) as conn:
        df = pd.read_sql(
            "SELECT * FROM dataset_manifest WHERE id = %s", conn, params=(dataset_id,)
        )
    if df.empty:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return df.iloc[0].to_dict()


@app.delete("/datasets/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: str):
    """Delete a dataset manifest record (does not remove S3 files)."""
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM dataset_manifest WHERE id = %s RETURNING id", (dataset_id,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Dataset not found")
        conn.commit()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=DATASET_BUILDER_PORT)
