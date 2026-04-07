import csv
import io
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "shared"))

from feature_columns import ALL_FEATURE_COLS
from .conftest import (
    DATASET_BUILDER_URL,
    FEATURE_BUILDER_URL,
    KAGGLE_ORCHESTRATOR_URL,
    S3_BUCKET,
)


def test_feature_build_populates_feature_row_with_all_20_columns(db_conn, built_features):
    result = built_features["SPY"]
    assert result["status"] == "ok"
    assert result["rows"] > 0

    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT ret_1d, ret_2d, ret_5d, ret_10d, ret_21d,
                   rsi, macd, atr, stoch, ultosc,
                   pe, pb, ps, evebitda, marketcap_log,
                   roe, roa, debt_equity, revenue_growth, fcf_yield
            FROM feature_row
            WHERE symbol = 'SPY'
            ORDER BY time DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()

    assert row is not None
    assert len(row) == len(ALL_FEATURE_COLS)
    assert all(value is not None for value in row)


def test_feature_availability_reports_backfilled_and_computed_rows(built_features):
    resp = requests.get(
        f"{FEATURE_BUILDER_URL}/features/availability",
        params={
            "symbols": "SPY",
            "start_date": "2024-01-01",
            "end_date": "2024-04-29",
        },
        timeout=20,
    )
    resp.raise_for_status()
    body = resp.json()["SPY"]

    assert body["bar_rows"] > 0
    assert body["feature_rows"] > 0
    assert body["feature_rows"] <= body["bar_rows"]


def test_dataset_build_and_export_preserve_full_feature_schema(s3_client, built_dataset):
    dataset_id = built_dataset["datasetId"]
    assert dataset_id
    assert built_dataset["nRows"] > 0
    assert built_dataset["nSplits"] == 2

    manifest_key = built_dataset["s3Path"]
    manifest_obj = s3_client.get_object(Bucket=S3_BUCKET, Key=manifest_key)
    manifest = json.loads(manifest_obj["Body"].read().decode())
    first_split_prefix = manifest["splits"][0]["s3_prefix"]

    train_obj = s3_client.get_object(Bucket=S3_BUCKET, Key=f"{first_split_prefix}/train.parquet")
    train_table = pq.read_table(io.BytesIO(train_obj["Body"].read()))
    train_columns = set(train_table.column_names)

    for col in ALL_FEATURE_COLS + ["open", "high", "low", "close", "volume", "symbol", "time"]:
        assert col in train_columns

    export_resp = requests.post(
        f"{DATASET_BUILDER_URL}/datasets/export",
        params={"symbols": ["SPY"], "format": "csv", "start_date": "2024-01-01", "end_date": "2024-04-29"},
        timeout=30,
    )
    export_resp.raise_for_status()

    csv_rows = list(csv.DictReader(io.StringIO(export_resp.text)))
    assert csv_rows
    for col in ALL_FEATURE_COLS + ["open", "high", "low", "close", "volume", "symbol", "time"]:
        assert col in csv_rows[0]


def test_kaggle_orchestrator_health_is_reachable(integration_env):
    resp = requests.get(f"{KAGGLE_ORCHESTRATOR_URL}/kaggle/health", timeout=10)
    resp.raise_for_status()
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "kaggle-orchestrator"
