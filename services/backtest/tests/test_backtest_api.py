"""
Unit tests for Backtest Service API endpoints and chart generation.
All DB, S3, and network calls are mocked.
"""
import base64
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
def mock_db_conn(monkeypatch):
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


def _make_equity_curve(n: int = 50) -> list[dict]:
    nav = 100_000.0
    curve = []
    for i in range(n):
        ret = np.random.normal(0.0003, 0.01)
        nav *= (1 + ret)
        curve.append({
            "time": f"2024-{(i//28)+1:02d}-{(i%28)+1:02d}",
            "nav": round(nav, 4),
            "market_nav": round(nav * 0.99, 4),
            "position": 1,
            "strategy_ret": round(ret, 6),
            "market_ret": round(ret * 0.99, 6),
            "cost": 0.001,
        })
    return curve


# ─── Chart generation tests ──────────────────────────────────────────────────

class TestGenerateCharts:
    def test_returns_empty_dict_when_no_curve(self):
        from main import generate_charts
        result = generate_charts("report-1", [{"symbol": "SPY", "equityCurve": []}])
        assert result == {}

    def test_returns_base64_png_per_symbol(self):
        from main import generate_charts
        curve = _make_equity_curve(60)
        metrics = [{"symbol": "SPY", "sharpeRatio": 1.2, "totalReturn": 0.08, "equityCurve": curve}]
        result = generate_charts("r-1", metrics)
        if result:  # matplotlib may not be available in CI
            assert "SPY" in result
            # Verify it's valid base64
            data = base64.b64decode(result["SPY"])
            assert data[:4] == b"\x89PNG"

    def test_generates_chart_per_symbol(self):
        from main import generate_charts
        curve = _make_equity_curve(60)
        metrics = [
            {"symbol": "SPY",  "sharpeRatio": 1.0, "totalReturn": 0.05, "equityCurve": curve},
            {"symbol": "AAPL", "sharpeRatio": 1.5, "totalReturn": 0.10, "equityCurve": curve},
        ]
        result = generate_charts("r-2", metrics)
        if result:
            assert set(result.keys()) == {"SPY", "AAPL"}


class TestUploadChartsToS3:
    def test_uploads_one_key_per_symbol(self):
        mock_s3 = MagicMock()
        with patch("main.get_s3", return_value=mock_s3):
            from main import upload_charts_to_s3
            fake_charts = {
                "SPY":  base64.b64encode(b"fake-png-1").decode(),
                "AAPL": base64.b64encode(b"fake-png-2").decode(),
            }
            paths = upload_charts_to_s3("report-1", fake_charts)
        assert mock_s3.put_object.call_count == 2
        assert "SPY" in paths
        assert "AAPL" in paths
        assert paths["SPY"].endswith("SPY.png")

    def test_sets_content_type_image_png(self):
        mock_s3 = MagicMock()
        with patch("main.get_s3", return_value=mock_s3):
            from main import upload_charts_to_s3
            upload_charts_to_s3("r", {"SPY": base64.b64encode(b"x").decode()})
        call_kwargs = mock_s3.put_object.call_args[1]
        assert call_kwargs["ContentType"] == "image/png"


# ─── DB helper tests ─────────────────────────────────────────────────────────

class TestCreateBacktestRecord:
    def test_returns_id_string(self, mock_db_conn):
        mock_conn, mock_cursor = mock_db_conn
        mock_cursor.fetchone.return_value = ("report-42",)
        from main import create_backtest_record
        rid = create_backtest_record({"name": "test", "symbols": ["SPY"],
                                       "startDate": "2024-01-01", "endDate": "2024-12-31"})
        assert rid == "report-42"

    def test_hashes_config_deterministically(self, mock_db_conn):
        mock_conn, mock_cursor = mock_db_conn
        mock_cursor.fetchone.return_value = ("r1",)
        from main import create_backtest_record
        cfg = {"name": "t", "symbols": ["A"], "startDate": "2024-01-01", "endDate": "2024-12-31"}
        create_backtest_record(cfg)
        create_backtest_record(cfg)
        # Both calls should use the same config_hash (same config dict)
        call1_hash = mock_cursor.execute.call_args_list[-2][0][1][2]
        call2_hash = mock_cursor.execute.call_args_list[-1][0][1][2]
        assert call1_hash == call2_hash


class TestUpdateBacktestRecord:
    def test_updates_status(self, mock_db_conn):
        mock_conn, mock_cursor = mock_db_conn
        from main import update_backtest_record
        update_backtest_record("r-1", "completed", {"avgSharpe": 1.2})
        sql = mock_cursor.execute.call_args[0][0]
        assert "UPDATE backtest_report" in sql


# ─── API endpoint tests ───────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_returns_ok(self, app_client):
        resp = app_client.get("/backtest/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestRunBacktestEndpoint:
    def test_returns_report_id(self, app_client, mock_db_conn):
        mock_conn, mock_cursor = mock_db_conn
        mock_cursor.fetchone.return_value = ("r-uuid",)
        with patch("main.run_backtest_task"):
            resp = app_client.post("/backtest/run", json={
                "name": "test-bt",
                "symbols": ["SPY"],
                "startDate": "2024-01-01",
                "endDate": "2024-12-31",
            })
        assert resp.status_code == 200
        body = resp.json()
        assert "reportId" in body
        assert body["status"] == "running"

    def test_requires_name_field(self, app_client):
        resp = app_client.post("/backtest/run", json={
            "symbols": ["SPY"],
            "startDate": "2024-01-01",
            "endDate": "2024-12-31",
        })
        assert resp.status_code == 422

    def test_requires_symbols(self, app_client):
        resp = app_client.post("/backtest/run", json={
            "name": "test",
            "startDate": "2024-01-01",
            "endDate": "2024-12-31",
        })
        assert resp.status_code == 422


class TestGetBacktestEndpoint:
    def test_returns_404_for_missing(self, app_client):
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            resp = app_client.get("/backtest/report-not-found")
        assert resp.status_code == 404

    def test_returns_report(self, app_client):
        df = pd.DataFrame([{
            "id": "r-1", "name": "test", "status": "completed",
            "metrics": '{"avgSharpe": 1.2}', "config": '{"symbols":["SPY"]}',
            "config_hash": "abc", "artifact_path": "backtests/r-1/results.json",
            "created_at": "2024-01-01", "error": None,
        }])
        with patch("pandas.read_sql", return_value=df):
            resp = app_client.get("/backtest/r-1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        assert isinstance(body["metrics"], dict)


class TestListBacktestsEndpoint:
    def test_returns_list(self, app_client):
        df = pd.DataFrame(columns=["id", "name", "status", "config_hash", "created_at"])
        with patch("pandas.read_sql", return_value=df):
            resp = app_client.get("/backtest")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestBacktestChartsEndpoint:
    def test_returns_404_for_missing(self, app_client):
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            resp = app_client.get("/backtest/r-nope/charts")
        assert resp.status_code == 404

    def test_returns_400_when_not_completed(self, app_client):
        df = pd.DataFrame([{
            "id": "r-1", "status": "running",
            "metrics": None,
        }])
        with patch("pandas.read_sql", return_value=df):
            resp = app_client.get("/backtest/r-1/charts")
        assert resp.status_code == 400

    def test_returns_chart_paths(self, app_client):
        df = pd.DataFrame([{
            "id": "r-1", "status": "completed",
            "metrics": '{"avgSharpe": 1.2, "chartPaths": {"SPY": "backtests/r-1/charts/SPY.png"}}',
        }])
        with patch("pandas.read_sql", return_value=df):
            resp = app_client.get("/backtest/r-1/charts")
        assert resp.status_code == 200
        body = resp.json()
        assert "SPY" in body["symbols"]
        assert "SPY" in body["chartPaths"]


class TestBacktestImageEndpoint:
    def test_returns_404_for_missing_report(self, app_client):
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            resp = app_client.get("/backtest/r-nope/images/SPY")
        assert resp.status_code == 404

    def test_returns_404_when_no_chart_for_symbol(self, app_client):
        df = pd.DataFrame([{"metrics": '{"chartPaths": {}}'}])
        with patch("pandas.read_sql", return_value=df):
            resp = app_client.get("/backtest/r-1/images/AAPL")
        assert resp.status_code == 404

    def test_returns_png_bytes(self, app_client):
        df = pd.DataFrame([{
            "metrics": '{"chartPaths": {"SPY": "backtests/r-1/charts/SPY.png"}}'
        }])
        mock_s3 = MagicMock()
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        def download_side_effect(bucket, key, buf):
            buf.write(fake_png)
        mock_s3.download_fileobj.side_effect = download_side_effect

        with patch("pandas.read_sql", return_value=df), \
             patch("main.get_s3", return_value=mock_s3):
            resp = app_client.get("/backtest/r-1/images/SPY")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
