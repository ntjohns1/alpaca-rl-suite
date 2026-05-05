import os
import sys
import io
import json
import hashlib
import logging
from contextlib import asynccontextmanager
from observability import setup_observability
from datetime import datetime, timezone

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import boto3
import psycopg2
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))
from keycloak_auth import keycloak_auth_from_env, make_auth_dependencies  # noqa: E402

_keycloak_auth = keycloak_auth_from_env()
get_current_user, _, _ = make_auth_dependencies(_keycloak_auth)

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
    Creates up to n_splits walk-forward (expanding window) train/test pairs.
    Each split's test window starts strictly after its train window.
    Returns list of dicts: {split, train_start, train_end, test_start, test_end}

    Requires at least n_splits + 1 unique dates in df.  Call-site should
    validate this before calling (see build_dataset).
    """
    df = df.sort_values("time")
    dates = df["time"].unique()
    n = len(dates)
    splits = []
    for i in range(1, n_splits + 1):
        train_end_idx = min(int(n * train_frac * i / n_splits), n - 2)
        test_start_idx = train_end_idx + 1
        if test_start_idx >= n:
            break
        # Distribute remaining dates evenly across remaining splits
        remaining_splits = n_splits - i + 1
        test_window = max(1, (n - test_start_idx) // remaining_splits)
        test_end_idx = min(test_start_idx + test_window - 1, n - 1)
        splits.append({
            "split": i,
            "train_start": str(dates[0]),
            "train_end":   str(dates[train_end_idx]),
            "test_start":  str(dates[test_start_idx]),
            "test_end":    str(dates[test_end_idx]),
        })
    return splits




def fetch_features(
    symbols: list[str], start_date: str, end_date: str, limit: Optional[int] = None
) -> pd.DataFrame:
    with psycopg2.connect(DATABASE_URL) as conn:
        placeholders = ",".join(["%s"] * len(symbols))
        if limit is not None:
            query = f"""
            SELECT f.time, f.symbol,
                   f.ret_1d, f.ret_2d, f.ret_5d, f.ret_10d, f.ret_21d,
                   f.rsi, f.macd, f.atr, f.stoch, f.ultosc,
                   f.pe, f.pb, f.ps, f.evebitda, f.marketcap_log,
                   f.roe, f.roa, f.debt_equity, f.revenue_growth, f.fcf_yield,
                   b.open::float  as open,
                   b.high::float  as high,
                   b.low::float   as low,
                   b.close::float as close,
                   b.volume::bigint as volume
            FROM feature_row f
            JOIN bar_1d b USING (time, symbol)
            WHERE f.symbol IN ({placeholders})
              AND f.time BETWEEN %s AND %s
            ORDER BY f.symbol, f.time
            LIMIT %s
            """
            params = (*symbols, start_date, end_date, int(limit))
        else:
            query = f"""
            SELECT f.time, f.symbol,
                   f.ret_1d, f.ret_2d, f.ret_5d, f.ret_10d, f.ret_21d,
                   f.rsi, f.macd, f.atr, f.stoch, f.ultosc,
                   f.pe, f.pb, f.ps, f.evebitda, f.marketcap_log,
                   f.roe, f.roa, f.debt_equity, f.revenue_growth, f.fcf_yield,
                   b.open::float  as open,
                   b.high::float  as high,
                   b.low::float   as low,
                   b.close::float as close,
                   b.volume::bigint as volume
            FROM feature_row f
            JOIN bar_1d b USING (time, symbol)
            WHERE f.symbol IN ({placeholders})
              AND f.time BETWEEN %s AND %s
            ORDER BY f.symbol, f.time
            """
            params = (*symbols, start_date, end_date)
        df = pd.read_sql(query, conn, params=params)
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


@app.get("/datasets/health")
def health():
    return {"status": "ok", "service": "dataset-builder"}


class BuildDatasetRequest(BaseModel):
    name: str
    symbols: list[str] = Field(..., min_length=1)
    start_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    n_splits: int = Field(default=5, ge=1)
    train_frac: float = Field(default=0.7, ge=0.0, lt=1.0)
    feature_version: str = "v2"

    @field_validator("end_date")
    @classmethod
    def end_after_start(cls, v: str, info) -> str:
        start = info.data.get("start_date")
        if start and v <= start:
            raise ValueError("end_date must be after start_date")
        return v


@app.post("/datasets/build")
def build_dataset(req: BuildDatasetRequest, _user: dict = Depends(get_current_user)):
    try:
        log.info(f"Building dataset '{req.name}' for {req.symbols}")
        df = fetch_features(req.symbols, req.start_date, req.end_date)
        if df.empty:
            raise HTTPException(status_code=422, detail="No feature data found for requested range")

        n_dates = len(df["time"].unique())
        if n_dates < req.n_splits + 1:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Not enough trading days ({n_dates}) for {req.n_splits} splits. "
                    f"Need at least {req.n_splits + 1} days, or reduce n_splits."
                ),
            )

        splits = build_walk_forward_splits(df, req.n_splits, req.train_frac)

        # Build config hash for reproducibility
        config = {
            "name": req.name, "symbols": sorted(req.symbols),
            "start_date": req.start_date, "end_date": req.end_date,
            "n_splits": req.n_splits, "train_frac": req.train_frac,
        }
        config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:12]

        # Upload each split as parquet — track written keys for rollback on failure
        split_paths = []
        uploaded_keys: list[str] = []
        try:
            for split in splits:
                train_df = df[(df["time"] >= split["train_start"]) & (df["time"] <= split["train_end"])]
                test_df  = df[(df["time"] >= split["test_start"])  & (df["time"] <= split["test_end"])]
                s3_prefix = f"datasets/{req.name}/{config_hash}/split_{split['split']}"
                train_key = f"{s3_prefix}/train.parquet"
                test_key  = f"{s3_prefix}/test.parquet"
                upload_parquet(train_df, train_key)
                uploaded_keys.append(train_key)
                upload_parquet(test_df, test_key)
                uploaded_keys.append(test_key)
                split_paths.append({**split, "s3_prefix": s3_prefix})
        except Exception:
            if uploaded_keys:
                try:
                    s3 = get_s3()
                    s3.delete_objects(
                        Bucket=S3_BUCKET,
                        Delete={"Objects": [{"Key": k} for k in uploaded_keys]},
                    )
                except Exception:
                    log.exception("S3 cleanup after partial upload failed")
            raise

        # Upload manifest JSON
        manifest_data = {**config, "config_hash": config_hash, "splits": split_paths,
                         "created_at": datetime.now(timezone.utc).isoformat()}
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
        log.exception(f"Dataset build failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/datasets")
def list_datasets(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _user: dict = Depends(get_current_user),
):
    with psycopg2.connect(DATABASE_URL) as conn:
        df = pd.read_sql(
            "SELECT * FROM dataset_manifest ORDER BY created_at DESC LIMIT %s OFFSET %s",
            conn,
            params=(limit, offset),
        )
    return df.to_dict("records")


@app.post("/datasets/export")
def export_dataset(
    symbols: list[str] = Query(...),
    format: str = Query(default="csv", pattern="^(csv|parquet)$"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    _user: dict = Depends(get_current_user),
):
    """
    Export feature data for given symbols to CSV or Parquet.
    Returns the file as a streaming download.
    """
    try:
        s_date = start_date or "2020-01-01"
        e_date = end_date   or datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
        log.exception(f"Export failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/datasets/preview")
def preview_dataset(
    symbols: list[str] = Query(...),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    rows: int = Query(default=20, ge=1, le=200),
    _user: dict = Depends(get_current_user),
):
    """Return a preview of feature data (up to `rows` rows per symbol)."""
    try:
        s_date = start_date or "2020-01-01"
        e_date = end_date   or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        df = fetch_features(symbols, s_date, e_date, limit=rows)
        if df.empty:
            raise HTTPException(status_code=422, detail="No data found")
        with psycopg2.connect(DATABASE_URL) as conn:
            placeholders = ",".join(["%s"] * len(symbols))
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT COUNT(*) FROM feature_row f "
                    f"JOIN bar_1d b USING (time, symbol) "
                    f"WHERE f.symbol IN ({placeholders}) AND f.time BETWEEN %s AND %s",
                    (*symbols, s_date, e_date),
                )
                count_row = cur.fetchone()
        total_rows = count_row[0] if count_row else len(df)
        preview = df.head(rows)
        return {
            "symbols":    symbols,
            "startDate":  s_date,
            "endDate":    e_date,
            "totalRows":  total_rows,
            "previewRows": len(preview),
            "columns":    list(df.columns),
            "data":       preview.to_dict("records"),
        }
    except HTTPException:
        raise
    except Exception as e:
        log.exception(f"Preview failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str, _user: dict = Depends(get_current_user)):
    with psycopg2.connect(DATABASE_URL) as conn:
        df = pd.read_sql(
            "SELECT * FROM dataset_manifest WHERE id = %s", conn, params=(dataset_id,)
        )
    if df.empty:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return df.iloc[0].to_dict()


@app.delete("/datasets/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: str, _user: dict = Depends(get_current_user)):
    """Delete a dataset manifest record, then clean up associated S3 objects best-effort."""
    # DB delete committed first — S3 cleanup is best-effort after.
    # Worst case with this ordering: S3 orphans (same as before this fix).
    # Worst case with the reverse ordering: a DB record pointing to deleted files.
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT s3_path FROM dataset_manifest WHERE id = %s", (dataset_id,)
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Dataset not found")
            s3_path: str = row[0]
            cur.execute("DELETE FROM dataset_manifest WHERE id = %s", (dataset_id,))
        conn.commit()

    # S3 cleanup — log failures, never 500 after a successful DB commit.
    try:
        s3_prefix = s3_path.rsplit("/", 1)[0] + "/"
        s3 = get_s3()
        paginator = s3.get_paginator("list_objects_v2")
        keys_to_delete: list[dict] = []
        for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=s3_prefix):
            for obj in page.get("Contents", []):
                keys_to_delete.append({"Key": obj["Key"]})
        for i in range(0, len(keys_to_delete), 1000):
            resp = s3.delete_objects(
                Bucket=S3_BUCKET,
                Delete={"Objects": keys_to_delete[i:i + 1000]},
            )
            errors = resp.get("Errors", [])
            if errors:
                log.warning("S3 delete_objects partial failure for %s: %s", s3_path, errors)
    except Exception:
        log.exception("S3 cleanup failed for %s — files may be orphaned", s3_path)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=DATASET_BUILDER_PORT)
