import json
import os
import time
from pathlib import Path

import boto3
import psycopg2
import pytest
import requests


ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SEED_SQL_PATH = FIXTURES_DIR / "seed_data.sql"

FEATURE_BUILDER_URL = os.getenv("FEATURE_BUILDER_URL", "http://localhost:18002")
DATASET_BUILDER_URL = os.getenv("DATASET_BUILDER_URL", "http://localhost:18003")
KAGGLE_ORCHESTRATOR_URL = os.getenv("KAGGLE_ORCHESTRATOR_URL", "http://localhost:18011")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://rl_user:rl_pass@localhost:15432/alpaca_rl")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://localhost:19000")
S3_BUCKET = os.getenv("S3_BUCKET", "alpaca-rl-artifacts")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "minioadmin")


def wait_for_http(url: str, timeout_s: int = 90) -> None:
    start = time.time()
    last_error = None
    while time.time() - start < timeout_s:
        try:
            resp = requests.get(url, timeout=3)
            if resp.ok:
                return
            last_error = f"{url} returned {resp.status_code}"
        except Exception as exc:  # pragma: no cover - integration helper
            last_error = str(exc)
        time.sleep(2)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def seed_database() -> None:
    sql = SEED_SQL_PATH.read_text()
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


def get_db_connection():
    return psycopg2.connect(DATABASE_URL)


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
    )


@pytest.fixture(scope="session")
def integration_env():
    wait_for_http(f"{FEATURE_BUILDER_URL}/features/health")
    wait_for_http(f"{DATASET_BUILDER_URL}/datasets/health")
    wait_for_http(f"{KAGGLE_ORCHESTRATOR_URL}/kaggle/health")
    seed_database()
    return {
        "feature_builder_url": FEATURE_BUILDER_URL,
        "dataset_builder_url": DATASET_BUILDER_URL,
        "kaggle_orchestrator_url": KAGGLE_ORCHESTRATOR_URL,
    }


@pytest.fixture
def db_conn(integration_env):
    with get_db_connection() as conn:
        yield conn


@pytest.fixture
def s3_client(integration_env):
    return get_s3_client()


@pytest.fixture
def built_features(integration_env):
    resp = requests.post(
        f"{FEATURE_BUILDER_URL}/features/build",
        json={"symbols": ["SPY"], "days": 120},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


@pytest.fixture
def built_dataset(integration_env, built_features):
    resp = requests.post(
        f"{DATASET_BUILDER_URL}/datasets/build",
        json={
            "name": "integration-spy-v2",
            "symbols": ["SPY"],
            "start_date": "2024-01-01",
            "end_date": "2024-04-29",
            "n_splits": 2,
            "train_frac": 0.7,
            "feature_version": "v2",
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()
