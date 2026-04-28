"""
Unit tests for RL Train Service API endpoints.
All DB, S3, and network calls are mocked.
"""
import os
import sys
from unittest.mock import MagicMock, patch

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
    monkeypatch.setattr("main.get_conn", lambda: mock_conn)
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


# ─── DB helper tests ─────────────────────────────────────────────────────────

class TestCreateRun:
    def test_returns_uuid_string(self, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = ("run-uuid-1",)
        from main import create_run
        run_id = create_run("my-run", {"symbols": ["SPY"], "totalTimesteps": 10000})
        assert run_id == "run-uuid-1"

    def test_inserts_running_status(self, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = ("run-1",)
        from main import create_run
        create_run("r", {"symbols": ["SPY"]})
        sql = mock_cursor.execute.call_args[0][0]
        assert "running" in sql


class TestUpdateRun:
    def test_sets_completed_at_on_terminal_status(self, mock_db):
        mock_conn, mock_cursor = mock_db
        from main import update_run
        for s in ("completed", "failed"):
            update_run("run-1", s, {})
            sql = mock_cursor.execute.call_args[0][0]
            assert "completed_at" in sql


class TestSavePolicyBundle:
    def test_returns_bundle_id(self, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = ("bundle-1",)
        from main import save_policy_bundle
        bid = save_policy_bundle("run-1", "s3://bucket/model.zip",
                                  {"name": "test"}, {"meanReward": 1.2})
        assert bid == "bundle-1"

    def test_inserts_with_correct_run_id(self, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = ("b-1",)
        from main import save_policy_bundle
        save_policy_bundle("run-xyz", "path", {"name": "t"}, {})
        call_params = mock_cursor.execute.call_args[0][1]
        assert "run-xyz" in call_params


# ─── API endpoint tests ───────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_returns_ok(self, app_client):
        resp = app_client.get("/rl/train/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert "cuda" in resp.json()


class TestStartTrainingEndpoint:
    def test_returns_run_id(self, app_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = ("run-uuid",)
        with patch("main.train"):
            resp = app_client.post("/rl/train", json={
                "name": "test-run",
                "symbols": ["SPY"],
            })
        assert resp.status_code == 200
        body = resp.json()
        assert "runId" in body
        assert body["status"] == "running"

    def test_requires_symbols(self, app_client):
        resp = app_client.post("/rl/train", json={"name": "bad"})
        assert resp.status_code == 422


class TestListRunsEndpoint:
    def test_returns_list(self, app_client):
        df = pd.DataFrame(columns=["id", "name", "status", "config_hash",
                                    "started_at", "completed_at"])
        with patch("pandas.read_sql", return_value=df):
            resp = app_client.get("/rl/runs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_respects_limit_param(self, app_client):
        df = pd.DataFrame(columns=["id", "name", "status", "config_hash",
                                    "started_at", "completed_at"])
        with patch("pandas.read_sql", return_value=df):
            resp = app_client.get("/rl/runs?limit=10")
        assert resp.status_code == 200


class TestGetRunEndpoint:
    def test_returns_404_for_missing(self, app_client):
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            resp = app_client.get("/rl/runs/no-such-run")
        assert resp.status_code == 404

    def test_returns_run_with_parsed_metrics(self, app_client):
        df = pd.DataFrame([{
            "id": "run-1", "name": "test", "status": "completed",
            "config_hash": "abc", "config": '{"symbols":["SPY"]}',
            "metrics": '{"meanReward": 1.5}',
            "started_at": "2024-01-01", "completed_at": "2024-01-02",
            "artifact_path": "models/run-1/policy_best.zip", "error": None,
        }])
        with patch("pandas.read_sql", return_value=df):
            resp = app_client.get("/rl/runs/run-1")
        assert resp.status_code == 200
        assert isinstance(resp.json()["metrics"], dict)
        assert resp.json()["metrics"]["meanReward"] == 1.5


class TestListPoliciesEndpoint:
    def test_returns_list(self, app_client):
        df = pd.DataFrame(columns=["id", "name", "version", "promoted",
                                    "approval_status", "approved_by",
                                    "approved_at", "created_at", "s3_path", "metrics"])
        with patch("pandas.read_sql", return_value=df):
            resp = app_client.get("/rl/policies")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_filters_by_approval_status(self, app_client):
        df = pd.DataFrame(columns=["id", "name", "version", "promoted",
                                    "approval_status", "approved_by",
                                    "approved_at", "created_at", "s3_path", "metrics"])
        with patch("pandas.read_sql", return_value=df):
            resp = app_client.get("/rl/policies?approval_status=approved")
        assert resp.status_code == 200


class TestGetPolicyEndpoint:
    def test_returns_404_for_missing(self, app_client):
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            resp = app_client.get("/rl/policies/no-such-policy")
        assert resp.status_code == 404

    def test_returns_policy_with_parsed_fields(self, app_client):
        df = pd.DataFrame([{
            "id": "pol-1", "name": "test-policy", "version": "1.0",
            "s3_path": "models/run-1/policy.zip",
            "config": '{"symbols":["SPY"]}',
            "metrics": '{"meanReward": 1.2}',
            "promoted": False, "approval_status": "pending",
            "approved_by": None, "approved_at": None,
            "created_at": "2024-01-01", "training_run_id": "run-1",
        }])
        with patch("pandas.read_sql", return_value=df):
            resp = app_client.get("/rl/policies/pol-1")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["config"], dict)
        assert isinstance(body["metrics"], dict)


class TestApprovePolicyEndpoint:
    def test_approves_policy(self, app_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.rowcount = 1
        # approved_by is intentionally NOT taken from the query string —
        # backend derives it from the validated JWT (preferred_username).
        resp = app_client.post("/rl/policies/pol-1/approve")
        assert resp.status_code == 200
        body = resp.json()
        assert body["approvalStatus"] == "approved"
        assert body["approvedBy"] == "test-user"

    def test_approve_ignores_client_supplied_identity(self, app_client, mock_db):
        """A forged ?approved_by=attacker query string must be ignored."""
        mock_conn, mock_cursor = mock_db
        mock_cursor.rowcount = 1
        resp = app_client.post("/rl/policies/pol-1/approve?approved_by=attacker")
        assert resp.status_code == 200
        assert resp.json()["approvedBy"] == "test-user"

    def test_returns_404_for_missing_policy(self, app_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.rowcount = 0
        resp = app_client.post("/rl/policies/no-such/approve")
        assert resp.status_code == 404


class TestRejectPolicyEndpoint:
    def test_rejects_policy_with_reason(self, app_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.rowcount = 1
        resp = app_client.post("/rl/policies/pol-1/reject?reason=low+sharpe")
        assert resp.status_code == 200
        body = resp.json()
        assert body["approvalStatus"] == "rejected"
        assert body["reason"] == "low sharpe"

    def test_returns_404_for_missing_policy(self, app_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.rowcount = 0
        resp = app_client.post("/rl/policies/no-such/reject")
        assert resp.status_code == 404


class TestPromotePolicyEndpoint:
    def test_promotes_approved_policy(self, app_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = ("approved",)
        resp = app_client.post("/rl/policies/pol-1/promote?promoted_by=admin")
        assert resp.status_code == 200
        body = resp.json()
        assert body["promoted"] is True

    def test_rejects_promotion_of_rejected_policy(self, app_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = ("rejected",)
        resp = app_client.post("/rl/policies/pol-1/promote")
        assert resp.status_code == 400

    def test_returns_404_for_missing_policy(self, app_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = None
        resp = app_client.post("/rl/policies/no-such/promote")
        assert resp.status_code == 404


class TestDownloadPolicyEndpoint:
    def test_returns_zip_bytes(self, app_client):
        df = pd.DataFrame([{
            "name": "my-policy",
            "s3_path": "models/run-1/policy.zip",
        }])
        mock_s3 = MagicMock()
        fake_zip = b"PK\x03\x04" + b"\x00" * 100
        def download_side(bucket, key, buf):
            buf.write(fake_zip)
        mock_s3.download_fileobj.side_effect = download_side

        with patch("pandas.read_sql", return_value=df), \
             patch("main.get_s3", return_value=mock_s3):
            resp = app_client.get("/rl/policies/pol-1/download")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"

    def test_returns_404_for_missing_policy(self, app_client):
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            resp = app_client.get("/rl/policies/no-such/download")
        assert resp.status_code == 404

    def test_returns_502_on_s3_error(self, app_client):
        df = pd.DataFrame([{"name": "p", "s3_path": "models/p.zip"}])
        mock_s3 = MagicMock()
        mock_s3.download_fileobj.side_effect = Exception("S3 error")
        with patch("pandas.read_sql", return_value=df), \
             patch("main.get_s3", return_value=mock_s3):
            resp = app_client.get("/rl/policies/pol-1/download")
        assert resp.status_code == 502


class TestDeletePolicyEndpoint:
    def test_returns_204_on_success(self, app_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.rowcount = 1
        resp = app_client.delete("/rl/policies/pol-1")
        assert resp.status_code == 204

    def test_returns_404_when_not_found(self, app_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.rowcount = 0
        resp = app_client.delete("/rl/policies/no-such")
        assert resp.status_code == 404
