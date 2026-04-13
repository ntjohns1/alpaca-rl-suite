"""
Unit tests for Dataset Builder Service.
All DB, S3, and network calls are mocked.
"""
import os
import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_db(monkeypatch):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = lambda s: s
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_conn.__enter__ = lambda s: s
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cursor
    monkeypatch.setattr("psycopg2.connect", lambda url: mock_conn)
    return mock_conn, mock_cursor


@pytest.fixture
def app_client():
    from main import app
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def _make_feature_df(n: int = 400, symbols=("SPY",)) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    dates = pd.date_range("2020-01-01", periods=n // len(symbols), freq="B")
    rows = []
    for sym in symbols:
        for d in dates:
            close = 100.0 + rng.normal(0, 5)
            rows.append({
                "time": d, "symbol": sym,
                "ret_1d":  rng.normal(0, 0.01),
                "ret_2d":  rng.normal(0, 0.01),
                "ret_5d":  rng.normal(0, 0.01),
                "ret_10d": rng.normal(0, 0.01),
                "ret_21d": rng.normal(0, 0.01),
                "rsi":    rng.uniform(20, 80),
                "macd":   rng.normal(0, 0.5),
                "atr":    rng.uniform(0.5, 3.0),
                "stoch":  rng.uniform(10, 90),
                "ultosc": rng.uniform(20, 80),
                "pe":     rng.uniform(10, 40),
                "pb":     rng.uniform(1, 10),
                "ps":     rng.uniform(1, 15),
                "evebitda": rng.uniform(5, 25),
                "marketcap_log": rng.uniform(20, 28),
                "roe":    rng.uniform(-0.1, 0.4),
                "roa":    rng.uniform(-0.05, 0.2),
                "debt_equity": rng.uniform(0, 3),
                "revenue_growth": rng.uniform(-0.2, 0.5),
                "fcf_yield": rng.uniform(-0.05, 0.15),
                "open":   close * rng.uniform(0.99, 1.0),
                "high":   close * rng.uniform(1.0, 1.01),
                "low":    close * rng.uniform(0.99, 1.0),
                "close":  close,
                "volume": int(rng.integers(1_000_000, 10_000_000)),
            })
    return pd.DataFrame(rows)


# ─── Walk-forward split tests ─────────────────────────────────────────────────

class TestBuildWalkForwardSplits:
    def test_returns_n_splits(self):
        from main import build_walk_forward_splits
        df = _make_feature_df(200)
        splits = build_walk_forward_splits(df, n_splits=5)
        assert len(splits) == 5

    def test_no_lookahead(self):
        from main import build_walk_forward_splits
        df = _make_feature_df(200)
        splits = build_walk_forward_splits(df, n_splits=3)
        for s in splits:
            assert s["train_end"] < s["test_start"], \
                f"Lookahead detected: train_end={s['train_end']} test_start={s['test_start']}"

    def test_splits_have_required_keys(self):
        from main import build_walk_forward_splits
        df = _make_feature_df(200)
        splits = build_walk_forward_splits(df, n_splits=2)
        for s in splits:
            for key in ("split", "train_start", "train_end", "test_start", "test_end"):
                assert key in s, f"Missing key: {key}"

    def test_split_numbers_are_sequential(self):
        from main import build_walk_forward_splits
        df = _make_feature_df(200)
        splits = build_walk_forward_splits(df, n_splits=4)
        for i, s in enumerate(splits, 1):
            assert s["split"] == i

    def test_respects_train_frac(self):
        from main import build_walk_forward_splits
        df = _make_feature_df(252)
        splits = build_walk_forward_splits(df, n_splits=1, train_frac=0.8)
        # Train window should cover ~80% of dates
        all_dates = sorted(df["time"].unique())
        train_dates = [d for d in all_dates if str(d) <= splits[0]["train_end"]]
        assert len(train_dates) / len(all_dates) >= 0.7  # allow some tolerance


# ─── Upload Parquet tests ─────────────────────────────────────────────────────

class TestUploadParquet:
    def test_calls_put_object(self):
        mock_s3 = MagicMock()
        with patch("main.get_s3", return_value=mock_s3):
            from main import upload_parquet
            df = _make_feature_df(50)
            path = upload_parquet(df, "datasets/test/train.parquet")
        mock_s3.put_object.assert_called_once()
        assert path == "datasets/test/train.parquet"

    def test_uploads_to_correct_bucket(self):
        mock_s3 = MagicMock()
        with patch("main.get_s3", return_value=mock_s3), \
             patch("main.S3_BUCKET", "alpaca-rl-artifacts"):
            from main import upload_parquet
            upload_parquet(_make_feature_df(20), "some/path.parquet")
        call_kwargs = mock_s3.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "alpaca-rl-artifacts"


# ─── API endpoint tests ───────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_returns_ok(self, app_client):
        resp = app_client.get("/datasets/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestBuildDatasetEndpoint:
    def test_returns_422_on_empty_data(self, app_client):
        with patch("main.fetch_features", return_value=pd.DataFrame()):
            resp = app_client.post("/datasets/build", json={
                "name": "test", "symbols": ["SPY"],
                "start_date": "2024-01-01", "end_date": "2024-12-31",
            })
        assert resp.status_code == 422

    def test_returns_dataset_id_on_success(self, app_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = ("dataset-uuid-1",)
        df = _make_feature_df(400)
        mock_s3 = MagicMock()
        with patch("main.fetch_features", return_value=df), \
             patch("main.upload_parquet", return_value="s3/path"), \
             patch("main.get_s3", return_value=mock_s3), \
             patch("main.register_manifest", return_value="dataset-uuid-1"):
            resp = app_client.post("/datasets/build", json={
                "name": "my-dataset",
                "symbols": ["SPY"],
                "start_date": "2020-01-01",
                "end_date": "2024-12-31",
            })
        assert resp.status_code == 200
        body = resp.json()
        assert "datasetId" in body
        assert body["name"] == "my-dataset"


class TestListDatasetsEndpoint:
    def test_returns_list(self, app_client):
        empty_df = pd.DataFrame(columns=["id", "name", "symbols",
                                          "start_date", "end_date", "created_at"])
        with patch("pandas.read_sql", return_value=empty_df):
            resp = app_client.get("/datasets")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestGetDatasetEndpoint:
    def test_returns_404_for_missing(self, app_client):
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            resp = app_client.get("/datasets/no-such-id")
        assert resp.status_code == 404

    def test_returns_dataset_row(self, app_client):
        df = pd.DataFrame([{
            "id": "d-1", "name": "test",
            "symbols": ["SPY"], "start_date": "2020-01-01",
            "end_date": "2024-12-31", "n_splits": 5,
            "s3_path": "datasets/test/manifest.json",
            "feature_version": "v1", "metadata": None, "created_at": "2024-01-01",
        }])
        with patch("pandas.read_sql", return_value=df):
            resp = app_client.get("/datasets/d-1")
        assert resp.status_code == 200
        assert resp.json()["name"] == "test"


class TestPreviewEndpoint:
    def test_returns_preview_data(self, app_client):
        df = _make_feature_df(50)
        with patch("main.fetch_features", return_value=df):
            resp = app_client.get("/datasets/preview?symbols=SPY&rows=5")
        assert resp.status_code == 200
        body = resp.json()
        assert body["previewRows"] <= 5
        assert "columns" in body
        assert "data" in body

    def test_returns_422_on_no_data(self, app_client):
        with patch("main.fetch_features", return_value=pd.DataFrame()):
            resp = app_client.get("/datasets/preview?symbols=SPY")
        assert resp.status_code == 422

    def test_respects_rows_param(self, app_client):
        df = _make_feature_df(100)
        with patch("main.fetch_features", return_value=df):
            resp = app_client.get("/datasets/preview?symbols=SPY&rows=10")
        assert resp.json()["previewRows"] == 10


class TestExportEndpoint:
    def test_exports_csv(self, app_client):
        df = _make_feature_df(30)
        with patch("main.fetch_features", return_value=df):
            resp = app_client.post("/datasets/export?symbols=SPY&format=csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]

    def test_exports_parquet(self, app_client):
        df = _make_feature_df(30)
        with patch("main.fetch_features", return_value=df):
            resp = app_client.post("/datasets/export?symbols=SPY&format=parquet")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/octet-stream"

    def test_returns_422_on_no_data(self, app_client):
        with patch("main.fetch_features", return_value=pd.DataFrame()):
            resp = app_client.post("/datasets/export?symbols=FAKE&format=csv")
        assert resp.status_code == 422

    def test_rejects_invalid_format(self, app_client):
        resp = app_client.post("/datasets/export?symbols=SPY&format=xlsx")
        assert resp.status_code == 422


class TestDeleteDatasetEndpoint:
    def test_returns_204_on_success(self, app_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.rowcount = 1
        resp = app_client.delete("/datasets/d-1")
        assert resp.status_code == 204

    def test_returns_404_when_not_found(self, app_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.rowcount = 0
        with patch("psycopg2.connect") as mock_connect:
            mock_c = MagicMock()
            mock_cur = MagicMock()
            mock_cur.__enter__ = lambda s: s
            mock_cur.__exit__ = MagicMock(return_value=False)
            mock_cur.rowcount = 0
            mock_c.__enter__ = lambda s: s
            mock_c.__exit__ = MagicMock(return_value=False)
            mock_c.cursor.return_value = mock_cur
            mock_connect.return_value = mock_c
            resp = app_client.delete("/datasets/no-such-id")
        assert resp.status_code == 404
