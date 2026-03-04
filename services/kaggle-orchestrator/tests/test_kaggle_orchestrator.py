"""
Unit tests for Kaggle Orchestrator Service.
All DB, S3, subprocess, and HTTP calls are mocked.
"""
import json
import os
import sys
from unittest.mock import MagicMock, patch, call

import pandas as pd
import pytest
from fastapi.testclient import TestClient

# Provide required env var before import
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─── Shared fixtures ────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_db_conn(monkeypatch):
    """Patch get_conn so no real DB is needed."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = lambda s: s
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_conn.__enter__ = lambda s: s
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cursor
    monkeypatch.setattr("main.get_conn", lambda: mock_conn)
    return mock_conn, mock_cursor


@pytest.fixture
def app_client(mock_db_conn):
    """TestClient for the FastAPI app (lifespan skipped)."""
    mock_conn, mock_cursor = mock_db_conn
    # lifespan creates the table — cursor.execute just needs to not fail
    mock_cursor.execute.return_value = None
    from main import app
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


# ─── DB helper tests ─────────────────────────────────────────────────────────

class TestCreateKaggleJob:
    def test_returns_uuid_string(self, mock_db_conn):
        mock_conn, mock_cursor = mock_db_conn
        mock_cursor.fetchone.return_value = ("abc-123",)

        import main
        job_id = main.create_kaggle_job("test-job", {"symbols": ["SPY"]})
        assert job_id == "abc-123"

    def test_inserts_with_pending_approval(self, mock_db_conn):
        mock_conn, mock_cursor = mock_db_conn
        mock_cursor.fetchone.return_value = ("uuid-1",)

        import main
        main.create_kaggle_job("my-run", {"symbols": ["AAPL"]})
        call_args = mock_cursor.execute.call_args
        assert "pending" in str(call_args)


class TestUpdateKaggleJob:
    def test_sets_completed_at_for_terminal_states(self, mock_db_conn):
        mock_conn, mock_cursor = mock_db_conn
        import main
        for status in ("completed", "failed", "cancelled"):
            main.update_kaggle_job("uuid-1", status)
            sql = mock_cursor.execute.call_args[0][0]
            assert "completed_at" in sql

    def test_passes_metadata_as_json(self, mock_db_conn):
        mock_conn, mock_cursor = mock_db_conn
        import main
        meta = {"policy_id": "p-1", "model_path": "s3://bucket/model.zip"}
        main.update_kaggle_job("uuid-1", "pending_approval", metadata=meta)
        # params tuple: (status, json_metadata, error, status, job_id)
        call_params = mock_cursor.execute.call_args[0][1]
        assert json.loads(call_params[1]) == meta


# ─── Business logic ───────────────────────────────────────────────────────────

class TestExportTrainingDataset:
    def test_raises_on_insufficient_data(self, mock_db_conn):
        mock_conn, _ = mock_db_conn
        small_df = pd.DataFrame({"date": range(10), "open": range(10),
                                  "high": range(10), "low": range(10),
                                  "close": range(10), "volume": range(10)})
        with patch("main.get_conn") as mock_gc:
            mock_gc.return_value.__enter__ = lambda s: s
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)
            with patch("pandas.read_sql", return_value=small_df):
                import main
                with pytest.raises(ValueError, match="Insufficient data"):
                    main.export_training_dataset("SPY", "/tmp/test.csv")

    def test_writes_csv_for_adequate_data(self, tmp_path, mock_db_conn):
        df = pd.DataFrame({
            "date":   pd.date_range("2020-01-01", periods=400),
            "open":   [100.0] * 400, "high": [101.0] * 400,
            "low":    [99.0]  * 400, "close": [100.5] * 400,
            "volume": [1000]  * 400,
        })
        out = str(tmp_path / "data.csv")
        with patch("main.get_conn") as mock_gc, \
             patch("pandas.read_sql", return_value=df):
            mock_gc.return_value.__enter__ = lambda s: s
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)
            import main
            result = main.export_training_dataset("SPY", out)
        assert result["rows"] == 400
        assert result["symbol"] == "SPY"


class TestKaggleRequest:
    def test_raises_without_api_token(self, monkeypatch):
        monkeypatch.setattr("main.KAGGLE_API_TOKEN", "")
        import main
        with pytest.raises(ValueError, match="KAGGLE_API_TOKEN"):
            main.kaggle_request("GET", "/test")

    def test_raises_on_http_error(self, monkeypatch):
        monkeypatch.setattr("main.KAGGLE_API_TOKEN", "tok-123")
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"
        mock_resp.content = b"Forbidden"
        mock_resp.raise_for_status.side_effect = Exception("403")
        with patch("requests.request", return_value=mock_resp):
            import main
            with pytest.raises(Exception):
                main.kaggle_request("GET", "/test")

    def test_returns_json_on_success(self, monkeypatch):
        monkeypatch.setattr("main.KAGGLE_API_TOKEN", "tok-123")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"userName": "testuser"}'
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"userName": "testuser"}
        with patch("requests.request", return_value=mock_resp):
            import main
            result = main.kaggle_request("GET", "/users/me")
        assert result["userName"] == "testuser"


class TestGetKernelStatus:
    def test_returns_unknown_on_exception(self, monkeypatch):
        monkeypatch.setattr("main.KAGGLE_API_TOKEN", "tok-123")
        with patch("main.kaggle_request", side_effect=Exception("network error")):
            import main
            status = main.get_kernel_status("my-kernel")
        assert status == "unknown"

    def test_returns_status_string(self, monkeypatch):
        monkeypatch.setattr("main.KAGGLE_API_TOKEN", "tok-123")
        with patch("main.kaggle_request", return_value={
            "currentRunningVersion": {"status": "complete"}
        }):
            import main
            status = main.get_kernel_status("my-kernel")
        assert status == "complete"


class TestTriggerBacktestForJob:
    def test_fires_and_forgets_on_success(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"reportId": "report-1"}
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.post", return_value=mock_resp) as mock_post:
            import main
            main.trigger_backtest_for_job("job-1", "policy-1", "SPY")
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["policyId"] == "policy-1"

    def test_does_not_raise_on_failure(self):
        with patch("requests.post", side_effect=Exception("connection refused")):
            import main
            # Should not raise — it's fire-and-forget
            main.trigger_backtest_for_job("job-1", "policy-1", "SPY")


# ─── API endpoint tests ───────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_returns_ok(self, app_client):
        resp = app_client.get("/kaggle/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["service"] == "kaggle-orchestrator"


class TestStartTrainingEndpoint:
    def test_returns_201_with_job_id(self, app_client, mock_db_conn):
        mock_conn, mock_cursor = mock_db_conn
        mock_cursor.fetchone.return_value = ("job-uuid-1",)
        with patch("main.orchestrate_kaggle_training"):
            resp = app_client.post("/kaggle/train", json={
                "name": "test-run",
                "symbols": ["SPY"],
            })
        assert resp.status_code == 201
        body = resp.json()
        assert "jobId" in body
        assert body["status"] == "preparing"

    def test_rejects_empty_symbols(self, app_client):
        resp = app_client.post("/kaggle/train", json={
            "name": "bad-run",
            "symbols": [],
        })
        assert resp.status_code == 422


class TestListJobsEndpoint:
    def test_returns_list(self, app_client, mock_db_conn):
        empty_df = pd.DataFrame(columns=[
            "id", "name", "status", "approval_status",
            "config_hash", "created_at", "updated_at", "completed_at"
        ])
        with patch("pandas.read_sql", return_value=empty_df):
            resp = app_client.get("/kaggle/jobs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_filters_by_status(self, app_client, mock_db_conn):
        empty_df = pd.DataFrame(columns=[
            "id", "name", "status", "approval_status",
            "config_hash", "created_at", "updated_at", "completed_at"
        ])
        with patch("pandas.read_sql", return_value=empty_df) as mock_sql:
            resp = app_client.get("/kaggle/jobs?status=pending_approval")
        assert resp.status_code == 200


class TestGetJobEndpoint:
    def test_returns_404_for_missing_job(self, app_client):
        empty_df = pd.DataFrame()
        with patch("pandas.read_sql", return_value=empty_df):
            resp = app_client.get("/kaggle/jobs/nonexistent-id")
        assert resp.status_code == 404

    def test_returns_job_row(self, app_client):
        job_df = pd.DataFrame([{
            "id": "job-1", "name": "test", "status": "training_on_kaggle",
            "approval_status": "pending", "config": '{"symbols":["SPY"]}',
            "metadata": None, "error": None, "config_hash": "abc",
            "created_at": "2024-01-01", "updated_at": "2024-01-01",
            "completed_at": None, "approved_by": None, "approved_at": None,
            "rejection_reason": None,
        }])
        with patch("pandas.read_sql", return_value=job_df):
            resp = app_client.get("/kaggle/jobs/job-1")
        assert resp.status_code == 200
        assert resp.json()["status"] == "training_on_kaggle"


class TestCancelJobEndpoint:
    def test_cancels_active_job(self, app_client, mock_db_conn):
        mock_conn, mock_cursor = mock_db_conn
        job_df = pd.DataFrame([{
            "id": "job-1", "name": "test", "status": "training_on_kaggle",
            "approval_status": "pending", "config": '{"symbols":["SPY"]}',
            "metadata": None, "error": None, "config_hash": "abc",
            "created_at": "2024-01-01", "updated_at": "2024-01-01",
            "completed_at": None, "approved_by": None, "approved_at": None,
            "rejection_reason": None,
        }])
        with patch("pandas.read_sql", return_value=job_df):
            resp = app_client.post("/kaggle/jobs/job-1/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_rejects_cancelling_completed_job(self, app_client):
        job_df = pd.DataFrame([{
            "id": "job-1", "name": "test", "status": "completed",
            "approval_status": "approved", "config": '{"symbols":["SPY"]}',
            "metadata": None, "error": None, "config_hash": "abc",
            "created_at": "2024-01-01", "updated_at": "2024-01-01",
            "completed_at": "2024-01-02", "approved_by": None, "approved_at": None,
            "rejection_reason": None,
        }])
        with patch("pandas.read_sql", return_value=job_df):
            resp = app_client.post("/kaggle/jobs/job-1/cancel")
        assert resp.status_code == 400


class TestApprovalEndpoints:
    def test_approve_pending_approval_job(self, app_client, mock_db_conn):
        mock_conn, mock_cursor = mock_db_conn
        job_df = pd.DataFrame([{
            "id": "job-1", "name": "test", "status": "pending_approval",
            "approval_status": "pending", "config": '{"symbols":["SPY"]}',
            "metadata": '{"policy_id":"pol-1"}',
            "error": None, "config_hash": "abc",
            "created_at": "2024-01-01", "updated_at": "2024-01-01",
            "completed_at": None, "approved_by": None, "approved_at": None,
            "rejection_reason": None,
        }])
        with patch("pandas.read_sql", return_value=job_df):
            resp = app_client.post(
                "/kaggle/jobs/job-1/approve-promotion",
                json={"approved_by": "alice"}
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["approvalStatus"] == "approved"
        assert body["approvedBy"] == "alice"

    def test_approve_fails_on_wrong_status(self, app_client):
        job_df = pd.DataFrame([{
            "id": "job-1", "name": "test", "status": "training_on_kaggle",
            "approval_status": "pending", "config": '{"symbols":["SPY"]}',
            "metadata": None, "error": None, "config_hash": "abc",
            "created_at": "2024-01-01", "updated_at": "2024-01-01",
            "completed_at": None, "approved_by": None, "approved_at": None,
            "rejection_reason": None,
        }])
        with patch("pandas.read_sql", return_value=job_df):
            resp = app_client.post(
                "/kaggle/jobs/job-1/approve-promotion",
                json={"approved_by": "alice"}
            )
        assert resp.status_code == 400

    def test_reject_pending_approval_job(self, app_client, mock_db_conn):
        mock_conn, mock_cursor = mock_db_conn
        job_df = pd.DataFrame([{
            "id": "job-1", "name": "test", "status": "pending_approval",
            "approval_status": "pending", "config": '{"symbols":["SPY"]}',
            "metadata": '{"policy_id":"pol-1"}',
            "error": None, "config_hash": "abc",
            "created_at": "2024-01-01", "updated_at": "2024-01-01",
            "completed_at": None, "approved_by": None, "approved_at": None,
            "rejection_reason": None,
        }])
        with patch("pandas.read_sql", return_value=job_df):
            resp = app_client.post(
                "/kaggle/jobs/job-1/reject-promotion",
                json={"reason": "poor Sharpe", "rejected_by": "bob"}
            )
        assert resp.status_code == 200
        assert resp.json()["approvalStatus"] == "rejected"

    def test_reject_fails_on_wrong_status(self, app_client):
        job_df = pd.DataFrame([{
            "id": "job-1", "name": "test", "status": "uploading_dataset",
            "approval_status": "pending", "config": '{"symbols":["SPY"]}',
            "metadata": None, "error": None, "config_hash": "abc",
            "created_at": "2024-01-01", "updated_at": "2024-01-01",
            "completed_at": None, "approved_by": None, "approved_at": None,
            "rejection_reason": None,
        }])
        with patch("pandas.read_sql", return_value=job_df):
            resp = app_client.post(
                "/kaggle/jobs/job-1/reject-promotion",
                json={"reason": "no"}
            )
        assert resp.status_code == 400


class TestQuotaEndpoint:
    def test_returns_quota_info(self, app_client, monkeypatch):
        monkeypatch.setattr("main.KAGGLE_API_TOKEN", "tok-123")
        with patch("main.kaggle_request", return_value={
            "userName": "testuser",
            "gpuQuotaUser": 30,
            "gpuQuotaUsed": 5,
        }):
            resp = app_client.get("/kaggle/quota")
        assert resp.status_code == 200
        body = resp.json()
        assert body["gpuRemaining"] == 25

    def test_returns_error_info_on_failure(self, app_client, monkeypatch):
        monkeypatch.setattr("main.KAGGLE_API_TOKEN", "tok-123")
        with patch("main.kaggle_request", side_effect=Exception("network error")):
            resp = app_client.get("/kaggle/quota")
        assert resp.status_code == 200
        assert "error" in resp.json()
