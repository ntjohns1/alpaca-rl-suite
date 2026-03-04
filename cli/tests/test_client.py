"""
Unit tests for AlpacaClient — covers _request error paths and all API methods.
"""
import sys
import os
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alpaca_rl.client import AlpacaClient, APIError


# ─── helpers ─────────────────────────────────────────────────────────────────

def _mock_response(status_code=200, json_data=None, content=b"", text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content if content else (str(json_data).encode() if json_data else b"")
    resp.text = text or (str(json_data) if json_data else "")
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("no json")
    return resp


# ─── _request core logic ─────────────────────────────────────────────────────

class TestRequestMethod:
    def setup_method(self):
        self.client = AlpacaClient(timeout=5)

    def test_returns_json_on_200(self):
        resp = _mock_response(200, json_data={"ok": True})
        with patch("requests.request", return_value=resp):
            result = self.client._request("GET", "http://example.com/test")
        assert result == {"ok": True}

    def test_returns_none_on_204(self):
        resp = _mock_response(204)
        resp.content = b""
        with patch("requests.request", return_value=resp):
            result = self.client._request("DELETE", "http://example.com/resource")
        assert result is None

    def test_returns_raw_bytes_when_json_fails(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b"binary-data"
        resp.json.side_effect = ValueError("not json")
        with patch("requests.request", return_value=resp):
            result = self.client._request("GET", "http://example.com/file")
        assert result == b"binary-data"

    def test_returns_none_when_no_content(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b""
        with patch("requests.request", return_value=resp):
            result = self.client._request("GET", "http://example.com")
        assert result is None

    def test_raises_api_error_on_4xx(self):
        resp = _mock_response(404, json_data={"detail": "not found"})
        with patch("requests.request", return_value=resp):
            with pytest.raises(APIError) as exc:
                self.client._request("GET", "http://example.com/missing")
        assert exc.value.status_code == 404
        assert "not found" in exc.value.detail

    def test_raises_api_error_on_5xx(self):
        resp = _mock_response(500, json_data={"detail": "server error"})
        with patch("requests.request", return_value=resp):
            with pytest.raises(APIError) as exc:
                self.client._request("GET", "http://example.com")
        assert exc.value.status_code == 500

    def test_api_error_falls_back_to_text_when_no_json(self):
        resp = MagicMock()
        resp.status_code = 422
        resp.content = b"Unprocessable"
        resp.text = "Unprocessable Entity"
        resp.json.side_effect = ValueError("no json")
        with patch("requests.request", return_value=resp):
            with pytest.raises(APIError) as exc:
                self.client._request("POST", "http://example.com")
        assert "Unprocessable" in exc.value.detail

    def test_exits_on_connection_error(self):
        import requests as req_lib
        with patch("requests.request", side_effect=req_lib.exceptions.ConnectionError()):
            with pytest.raises(SystemExit):
                self.client._request("GET", "http://localhost:9999/unreachable")

    def test_exits_on_timeout(self):
        import requests as req_lib
        with patch("requests.request", side_effect=req_lib.exceptions.Timeout()):
            with pytest.raises(SystemExit):
                self.client._request("GET", "http://localhost:9999/slow")

    def test_get_delegates_to_request(self):
        resp = _mock_response(200, json_data={"result": "ok"})
        with patch("requests.request", return_value=resp) as mock_req:
            self.client.get("http://example.com/api", params={"k": "v"})
        mock_req.assert_called_once_with("GET", "http://example.com/api",
                                         timeout=5, params={"k": "v"})

    def test_post_delegates_to_request(self):
        resp = _mock_response(201, json_data={"id": "abc"})
        with patch("requests.request", return_value=resp) as mock_req:
            self.client.post("http://example.com/api", json={"name": "test"})
        mock_req.assert_called_once_with("POST", "http://example.com/api",
                                         timeout=5, json={"name": "test"})

    def test_delete_delegates_to_request(self):
        resp = _mock_response(204)
        resp.content = b""
        with patch("requests.request", return_value=resp) as mock_req:
            self.client.delete("http://example.com/api/item-1")
        mock_req.assert_called_once_with("DELETE", "http://example.com/api/item-1", timeout=5)


# ─── Kaggle methods ───────────────────────────────────────────────────────────

class TestKaggleMethods:
    def setup_method(self):
        self.client = AlpacaClient()
        self.client._request = MagicMock(return_value={"jobId": "j-1"})

    def test_kaggle_train(self):
        self.client.kaggle_train({"name": "run", "symbols": ["SPY"]})
        self.client._request.assert_called_once()
        url = self.client._request.call_args[0][1]
        assert "/kaggle/train" in url

    def test_kaggle_list_jobs_no_filters(self):
        self.client._request.return_value = []
        self.client.kaggle_list_jobs()
        url = self.client._request.call_args[0][1]
        assert "/kaggle/jobs" in url

    def test_kaggle_list_jobs_with_filters(self):
        self.client._request.return_value = []
        self.client.kaggle_list_jobs(status="running", approval_status="pending")
        kwargs = self.client._request.call_args[1]
        assert kwargs["params"]["status"] == "running"
        assert kwargs["params"]["approval_status"] == "pending"

    def test_kaggle_get_job(self):
        self.client.kaggle_get_job("j-1")
        url = self.client._request.call_args[0][1]
        assert "j-1" in url

    def test_kaggle_cancel_job(self):
        self.client.kaggle_cancel_job("j-1")
        url = self.client._request.call_args[0][1]
        assert "cancel" in url

    def test_kaggle_approve(self):
        self.client.kaggle_approve("j-1", approved_by="alice")
        url = self.client._request.call_args[0][1]
        assert "approve-promotion" in url

    def test_kaggle_reject(self):
        self.client.kaggle_reject("j-1", reason="poor metrics")
        url = self.client._request.call_args[0][1]
        assert "reject-promotion" in url

    def test_kaggle_quota(self):
        self.client.kaggle_quota()
        url = self.client._request.call_args[0][1]
        assert "/kaggle/quota" in url


# ─── Backtest methods ─────────────────────────────────────────────────────────

class TestBacktestMethods:
    def setup_method(self):
        self.client = AlpacaClient()
        self.client._request = MagicMock(return_value={"reportId": "r-1"})

    def test_backtest_run(self):
        self.client.backtest_run({"name": "bt", "symbols": ["SPY"],
                                  "startDate": "2022-01-01", "endDate": "2022-12-31"})
        url = self.client._request.call_args[0][1]
        assert "/backtest/run" in url

    def test_backtest_get(self):
        self.client.backtest_get("r-1")
        url = self.client._request.call_args[0][1]
        assert "r-1" in url

    def test_backtest_list(self):
        self.client._request.return_value = []
        self.client.backtest_list(limit=10)
        kwargs = self.client._request.call_args[1]
        assert kwargs["params"]["limit"] == 10

    def test_backtest_charts(self):
        self.client.backtest_charts("r-1")
        url = self.client._request.call_args[0][1]
        assert "charts" in url


# ─── Policy methods ───────────────────────────────────────────────────────────

class TestPolicyMethods:
    def setup_method(self):
        self.client = AlpacaClient()
        self.client._request = MagicMock(return_value={"policyId": "p-1"})

    def test_policy_list_no_filter(self):
        self.client._request.return_value = []
        self.client.policy_list()
        url = self.client._request.call_args[0][1]
        assert "/rl/policies" in url

    def test_policy_list_promoted_only(self):
        self.client._request.return_value = []
        self.client.policy_list(promoted_only=True)
        kwargs = self.client._request.call_args[1]
        assert kwargs["params"]["promoted_only"] == "true"

    def test_policy_list_with_approval_status(self):
        self.client._request.return_value = []
        self.client.policy_list(approval_status="approved")
        kwargs = self.client._request.call_args[1]
        assert kwargs["params"]["approval_status"] == "approved"

    def test_policy_get(self):
        self.client.policy_get("p-1")
        url = self.client._request.call_args[0][1]
        assert "p-1" in url

    def test_policy_approve(self):
        self.client.policy_approve("p-1", approved_by="bob")
        url = self.client._request.call_args[0][1]
        assert "approve" in url

    def test_policy_reject(self):
        self.client.policy_reject("p-1", reason="low sharpe")
        url = self.client._request.call_args[0][1]
        assert "reject" in url

    def test_policy_promote(self):
        self.client.policy_promote("p-1", promoted_by="admin")
        url = self.client._request.call_args[0][1]
        assert "promote" in url

    def test_policy_download(self):
        self.client._request.return_value = b"zip-data"
        result = self.client.policy_download("p-1")
        url = self.client._request.call_args[0][1]
        assert "download" in url

    def test_policy_delete(self):
        self.client._request.return_value = None
        self.client.policy_delete("p-1")
        url = self.client._request.call_args[0][1]
        assert "p-1" in url


# ─── Dataset methods ──────────────────────────────────────────────────────────

class TestDatasetMethods:
    def setup_method(self):
        self.client = AlpacaClient()
        self.client._request = MagicMock(return_value={"id": "d-1"})

    def test_dataset_list(self):
        self.client._request.return_value = []
        self.client.dataset_list()
        url = self.client._request.call_args[0][1]
        assert "/datasets" in url

    def test_dataset_get(self):
        self.client.dataset_get("d-1")
        url = self.client._request.call_args[0][1]
        assert "d-1" in url

    def test_dataset_export_basic(self):
        self.client._request.return_value = b"csv-data"
        self.client.dataset_export(["SPY"])
        url = self.client._request.call_args[0][1]
        assert "export" in url

    def test_dataset_export_with_dates(self):
        self.client._request.return_value = b"csv-data"
        self.client.dataset_export(["SPY"], format="parquet",
                                   start_date="2022-01-01", end_date="2022-12-31")
        kwargs = self.client._request.call_args[1]
        assert kwargs["params"]["start_date"] == "2022-01-01"
        assert kwargs["params"]["end_date"] == "2022-12-31"

    def test_dataset_preview_basic(self):
        self.client.dataset_preview(["SPY"])
        url = self.client._request.call_args[0][1]
        assert "preview" in url

    def test_dataset_preview_with_dates(self):
        self.client.dataset_preview(["SPY"], start_date="2022-01-01",
                                    end_date="2022-12-31", rows=50)
        kwargs = self.client._request.call_args[1]
        assert kwargs["params"]["rows"] == 50
        assert kwargs["params"]["start_date"] == "2022-01-01"

    def test_dataset_delete(self):
        self.client._request.return_value = None
        self.client.dataset_delete("d-1")
        url = self.client._request.call_args[0][1]
        assert "d-1" in url


# ─── System methods ───────────────────────────────────────────────────────────

class TestSystemMethods:
    def setup_method(self):
        self.client = AlpacaClient()
        self.client._request = MagicMock(return_value={"status": "ok"})

    def test_system_overview(self):
        self.client.system_overview()
        url = self.client._request.call_args[0][1]
        assert "overview" in url

    def test_system_services(self):
        self.client.system_services()
        url = self.client._request.call_args[0][1]
        assert "services" in url

    def test_system_activity(self):
        self.client.system_activity(limit=10)
        kwargs = self.client._request.call_args[1]
        assert kwargs["params"]["limit"] == 10
