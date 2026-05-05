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
    from main import app, get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"preferred_username": "test-user"}
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_current_user, None)


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

    def test_no_index_error_on_minimum_data(self):
        """n_splits+1 dates should never raise IndexError (the regression case)."""
        from main import build_walk_forward_splits
        # 6 dates for n_splits=5 — smallest valid input
        dates = pd.date_range("2024-01-01", periods=6, freq="B")
        df = pd.DataFrame({
            "time": list(dates) * 1,
            "symbol": ["SPY"] * 6,
            "close": [100.0] * 6,
        })
        splits = build_walk_forward_splits(df, n_splits=5)
        assert len(splits) >= 1  # at least one valid split was produced

    def test_train_end_strictly_before_test_start_on_small_data(self):
        """No lookahead even on tiny date ranges."""
        from main import build_walk_forward_splits
        dates = pd.date_range("2024-01-01", periods=10, freq="B")
        df = pd.DataFrame({
            "time": list(dates),
            "symbol": ["SPY"] * 10,
            "close": [100.0] * 10,
        })
        splits = build_walk_forward_splits(df, n_splits=5)
        for s in splits:
            assert s["train_end"] < s["test_start"], \
                f"Lookahead on small data: train_end={s['train_end']} test_start={s['test_start']}"

    def test_all_dates_within_bounds(self):
        """train_start, train_end, test_start, test_end must all be real dates in df."""
        from main import build_walk_forward_splits
        df = _make_feature_df(60)
        valid_dates = set(str(d) for d in df["time"].unique())
        splits = build_walk_forward_splits(df, n_splits=4)
        for s in splits:
            for key in ("train_start", "train_end", "test_start", "test_end"):
                assert s[key] in valid_dates, \
                    f"Split date {s[key]} not in original date set"


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

    def test_total_rows_reflects_full_count(self, app_client):
        """totalRows must come from COUNT(*), not len(preview)."""
        df = _make_feature_df(50)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: s
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = (50,)
        mock_conn.cursor.return_value = mock_cur
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)
        with patch("main.fetch_features", return_value=df.head(5)), \
             patch("psycopg2.connect", return_value=mock_conn):
            resp = app_client.get("/datasets/preview?symbols=SPY&rows=5")
        assert resp.status_code == 200
        body = resp.json()
        assert body["totalRows"] == 50
        assert body["previewRows"] == 5


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
    def _make_delete_mock(self, s3_path=None, found=True):
        """Return a psycopg2.connect mock suitable for delete_dataset."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (s3_path,) if found else None
        return mock_conn, mock_cursor

    def test_returns_204_on_success(self, app_client):
        mock_conn, mock_cursor = self._make_delete_mock(s3_path="datasets/test/abc123/manifest.json")
        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"Contents": [{"Key": "datasets/test/abc123/manifest.json"}]}]
        mock_s3.get_paginator.return_value = mock_paginator
        with patch("psycopg2.connect", return_value=mock_conn), \
             patch("main.get_s3", return_value=mock_s3):
            resp = app_client.delete("/datasets/d-1")
        assert resp.status_code == 204
        mock_s3.delete_objects.assert_called_once()
        executed_sql = [str(c.args[0]) for c in mock_cursor.execute.call_args_list]
        assert any("DELETE" in sql for sql in executed_sql)

    def test_deletes_all_s3_objects_for_prefix(self, app_client):
        """All S3 objects under the dataset prefix must appear in delete_objects."""
        s3_path = "datasets/myds/deadbeef1234/manifest.json"
        mock_conn, mock_cursor = self._make_delete_mock(s3_path=s3_path)
        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{
            "Contents": [
                {"Key": "datasets/myds/deadbeef1234/manifest.json"},
                {"Key": "datasets/myds/deadbeef1234/split_1/train.parquet"},
                {"Key": "datasets/myds/deadbeef1234/split_1/test.parquet"},
            ]
        }]
        mock_s3.get_paginator.return_value = mock_paginator
        with patch("psycopg2.connect", return_value=mock_conn), \
             patch("main.get_s3", return_value=mock_s3):
            resp = app_client.delete("/datasets/d-1")
        assert resp.status_code == 204
        call_kwargs = mock_s3.delete_objects.call_args[1]
        deleted_keys = [o["Key"] for o in call_kwargs["Delete"]["Objects"]]
        assert "datasets/myds/deadbeef1234/split_1/train.parquet" in deleted_keys
        assert "datasets/myds/deadbeef1234/split_1/test.parquet" in deleted_keys

    def test_s3_cleanup_failure_does_not_return_500(self, app_client):
        """DB is already committed — an S3 error must not cause a 500."""
        mock_conn, mock_cursor = self._make_delete_mock(s3_path="datasets/test/abc123/manifest.json")
        mock_s3 = MagicMock()
        mock_s3.get_paginator.side_effect = RuntimeError("S3 unreachable")
        with patch("psycopg2.connect", return_value=mock_conn), \
             patch("main.get_s3", return_value=mock_s3):
            resp = app_client.delete("/datasets/d-1")
        assert resp.status_code == 204

    def test_partial_s3_delete_errors_are_logged(self, app_client, caplog):
        """Partial delete_objects failures are logged as warnings, not raised."""
        import logging
        mock_conn, mock_cursor = self._make_delete_mock(s3_path="datasets/test/abc123/manifest.json")
        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"Contents": [{"Key": "datasets/test/abc123/manifest.json"}]}]
        mock_s3.get_paginator.return_value = mock_paginator
        mock_s3.delete_objects.return_value = {
            "Errors": [{"Key": "datasets/test/abc123/manifest.json", "Code": "AccessDenied"}]
        }
        with patch("psycopg2.connect", return_value=mock_conn), \
             patch("main.get_s3", return_value=mock_s3), \
             caplog.at_level(logging.WARNING, logger="main"):
            resp = app_client.delete("/datasets/d-1")
        assert resp.status_code == 204
        assert any("partial failure" in r.message for r in caplog.records)

    def test_returns_404_when_not_found(self, app_client):
        mock_conn, mock_cursor = self._make_delete_mock(found=False)
        mock_s3 = MagicMock()
        with patch("psycopg2.connect", return_value=mock_conn), \
             patch("main.get_s3", return_value=mock_s3):
            resp = app_client.delete("/datasets/no-such-id")
        assert resp.status_code == 404
        mock_s3.delete_objects.assert_not_called()


class TestBuildDatasetRequestValidation:
    def test_rejects_empty_symbols(self, app_client):
        resp = app_client.post("/datasets/build", json={
            "name": "test", "symbols": [],
            "start_date": "2020-01-01", "end_date": "2024-12-31",
        })
        assert resp.status_code == 422

    def test_rejects_invalid_date_format(self, app_client):
        resp = app_client.post("/datasets/build", json={
            "name": "test", "symbols": ["SPY"],
            "start_date": "01/01/2020", "end_date": "2024-12-31",
        })
        assert resp.status_code == 422

    def test_rejects_end_before_start(self, app_client):
        resp = app_client.post("/datasets/build", json={
            "name": "test", "symbols": ["SPY"],
            "start_date": "2024-12-31", "end_date": "2020-01-01",
        })
        assert resp.status_code == 422

    def test_rejects_zero_n_splits(self, app_client):
        resp = app_client.post("/datasets/build", json={
            "name": "test", "symbols": ["SPY"],
            "start_date": "2020-01-01", "end_date": "2024-12-31",
            "n_splits": 0,
        })
        assert resp.status_code == 422

    def test_rejects_train_frac_gte_1(self, app_client):
        resp = app_client.post("/datasets/build", json={
            "name": "test", "symbols": ["SPY"],
            "start_date": "2020-01-01", "end_date": "2024-12-31",
            "train_frac": 1.0,
        })
        assert resp.status_code == 422


class TestPartialUploadCleanup:
    def test_cleans_up_partial_uploads_on_s3_failure(self, app_client, mock_db):
        """If upload_parquet raises on split 2, already-uploaded keys must be deleted."""
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = ("dataset-uuid-1",)
        df = _make_feature_df(400)
        call_count = 0

        def flaky_upload(data, path):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise RuntimeError("S3 timeout")
            return path

        mock_s3 = MagicMock()
        with patch("main.fetch_features", return_value=df), \
             patch("main.upload_parquet", side_effect=flaky_upload), \
             patch("main.get_s3", return_value=mock_s3):
            resp = app_client.post("/datasets/build", json={
                "name": "my-dataset", "symbols": ["SPY"],
                "start_date": "2020-01-01", "end_date": "2024-12-31",
            })
        assert resp.status_code == 500
        mock_s3.delete_objects.assert_called_once()
        deleted = mock_s3.delete_objects.call_args[1]["Delete"]["Objects"]
        assert len(deleted) == 1


class TestListDatasetsPagination:
    def test_accepts_limit_and_offset(self, app_client):
        empty_df = pd.DataFrame(columns=["id", "name", "symbols",
                                          "start_date", "end_date", "created_at"])
        with patch("pandas.read_sql", return_value=empty_df) as mock_sql:
            resp = app_client.get("/datasets?limit=10&offset=20")
        assert resp.status_code == 200
        call_args = mock_sql.call_args
        assert call_args[1]["params"] == (10, 20)
