"""
Unit tests for Dashboard Service.
All DB and HTTP calls to downstream services are mocked.
"""
import json
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
    from main import app
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


# ─── Unit: check_service_health ──────────────────────────────────────────────

class TestCheckServiceHealth:
    def test_returns_ok_on_200(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.elapsed.total_seconds.return_value = 0.05
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock_resp):
            from main import check_service_health
            result = check_service_health("backtest", "http://backtest:8001/health")
        assert result["status"] == "ok"
        assert result["service"] == "backtest"
        assert isinstance(result["latencyMs"], int)

    def test_returns_unreachable_on_connection_error(self):
        import requests as req
        with patch("requests.get", side_effect=req.exceptions.ConnectionError()):
            from main import check_service_health
            result = check_service_health("backtest", "http://backtest:8001/health")
        assert result["status"] == "unreachable"
        assert result["latencyMs"] is None

    def test_returns_timeout_on_timeout(self):
        import requests as req
        with patch("requests.get", side_effect=req.exceptions.Timeout()):
            from main import check_service_health
            result = check_service_health("backtest", "http://backtest:8001/health")
        assert result["status"] == "timeout"
        assert result["latencyMs"] is None

    def test_returns_error_on_http_error(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("500 Server Error")
        with patch("requests.get", return_value=mock_resp):
            from main import check_service_health
            result = check_service_health("backtest", "http://backtest:8001/health")
        assert result["status"] == "error"


# ─── Unit: get_system_stats ───────────────────────────────────────────────────

class TestGetSystemStats:
    def test_returns_all_keys(self, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = (0,)
        mock_cursor.fetchall.return_value = []
        from main import get_system_stats
        stats = get_system_stats()
        for key in (
            "totalTrainingJobs", "completedJobs", "failedJobs",
            "pendingApprovals", "promotedPolicies",
            "totalBacktests", "completedBacktests", "totalDatasets",
        ):
            assert key in stats, f"Missing key: {key}"

    def test_counts_pending_approvals(self, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchall.side_effect = [
            [("pending_approval", 3), ("completed", 10), ("failed", 1)],  # kaggle jobs
            [("running", 2), ("completed", 5)],  # backtests
        ]
        mock_cursor.fetchone.return_value = (2,)  # promoted policies / dataset count
        from main import get_system_stats
        stats = get_system_stats()
        assert stats["pendingApprovals"] == 3

    def test_returns_zeros_on_db_error(self, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchall.side_effect = Exception("DB error")
        from main import get_system_stats
        stats = get_system_stats()
        assert stats["totalTrainingJobs"] == 0


# ─── Unit: get_recent_activity ────────────────────────────────────────────────

class TestGetRecentActivity:
    def test_returns_sorted_events(self, mock_db):
        jobs_df = pd.DataFrame([{
            "id": "j-1", "name": "job-1", "status": "completed",
            "approval_status": "approved", "updated_at": "2024-06-01",
        }])
        bt_df = pd.DataFrame([{
            "id": "r-1", "name": "bt-1", "status": "completed",
            "created_at": "2024-07-01",
        }])
        with patch("pandas.read_sql", side_effect=[jobs_df, bt_df]):
            from main import get_recent_activity
            events = get_recent_activity(limit=10)
        assert len(events) == 2
        # Most recent first
        assert events[0]["timestamp"] > events[1]["timestamp"]

    def test_returns_empty_on_db_error(self, mock_db):
        with patch("pandas.read_sql", side_effect=Exception("DB error")):
            from main import get_recent_activity
            events = get_recent_activity()
        assert events == []

    def test_event_has_required_fields(self, mock_db):
        jobs_df = pd.DataFrame([{
            "id": "j-1", "name": "job-1", "status": "completed",
            "approval_status": "approved", "updated_at": "2024-01-01",
        }])
        bt_df = pd.DataFrame(columns=["id", "name", "status", "created_at"])
        with patch("pandas.read_sql", side_effect=[jobs_df, bt_df]):
            from main import get_recent_activity
            events = get_recent_activity()
        assert events[0]["type"] == "training_job"
        for field in ("type", "id", "name", "status", "timestamp"):
            assert field in events[0]


# ─── API endpoint tests ───────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_returns_ok(self, app_client):
        resp = app_client.get("/dashboard/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["service"] == "dashboard"


class TestOverviewEndpoint:
    def test_returns_overview_structure(self, app_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.return_value = (0,)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.elapsed.total_seconds.return_value = 0.01
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock_resp):
            resp = app_client.get("/dashboard/overview")
        assert resp.status_code == 200
        body = resp.json()
        assert "systemStatus" in body
        assert "services" in body
        assert "stats" in body
        assert "pendingApprovals" in body
        assert "activeJobs" in body

    def test_healthy_when_all_services_ok(self, app_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.return_value = (0,)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.elapsed.total_seconds.return_value = 0.01
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock_resp):
            resp = app_client.get("/dashboard/overview")
        assert resp.json()["systemStatus"] == "healthy"

    def test_degraded_when_service_unreachable(self, app_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.return_value = (0,)
        import requests as req
        with patch("requests.get", side_effect=req.exceptions.ConnectionError()):
            resp = app_client.get("/dashboard/overview")
        assert resp.json()["systemStatus"] == "degraded"


class TestServicesEndpoint:
    def test_returns_services_list(self, app_client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.elapsed.total_seconds.return_value = 0.01
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock_resp):
            resp = app_client.get("/dashboard/services")
        assert resp.status_code == 200
        body = resp.json()
        assert "services" in body
        assert "checkedAt" in body
        assert len(body["services"]) == 4  # 4 registered services


class TestActivityEndpoint:
    def test_returns_events_list(self, app_client, mock_db):
        jobs_df = pd.DataFrame(columns=["id", "name", "status", "approval_status", "updated_at"])
        bt_df = pd.DataFrame(columns=["id", "name", "status", "created_at"])
        with patch("pandas.read_sql", side_effect=[jobs_df, bt_df]):
            resp = app_client.get("/dashboard/activity")
        assert resp.status_code == 200
        body = resp.json()
        assert "events" in body
        assert "generatedAt" in body

    def test_respects_limit_param(self, app_client, mock_db):
        jobs_df = pd.DataFrame(columns=["id", "name", "status", "approval_status", "updated_at"])
        bt_df = pd.DataFrame(columns=["id", "name", "status", "created_at"])
        with patch("pandas.read_sql", side_effect=[jobs_df, bt_df]):
            resp = app_client.get("/dashboard/activity?limit=5")
        assert resp.status_code == 200

    def test_rejects_limit_over_100(self, app_client):
        resp = app_client.get("/dashboard/activity?limit=999")
        assert resp.status_code == 422
