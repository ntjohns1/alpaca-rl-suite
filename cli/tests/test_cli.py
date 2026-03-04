"""
Unit tests for the alpaca-rl CLI.
All HTTP calls to services are mocked via AlpacaClient.
"""
import sys
import os
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alpaca_rl.main import cli
from alpaca_rl.client import APIError


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def mock_client(monkeypatch):
    """Patch AlpacaClient in every command module."""
    mock = MagicMock()
    for mod in (
        "alpaca_rl.commands.train",
        "alpaca_rl.commands.policy",
        "alpaca_rl.commands.backtest",
        "alpaca_rl.commands.dataset",
        "alpaca_rl.commands.system",
    ):
        monkeypatch.setattr(f"{mod}.client", mock)
    return mock


# ─── train commands ───────────────────────────────────────────────────────────

class TestTrainStartCommand:
    def test_start_training_success(self, runner, mock_client):
        mock_client.kaggle_train.return_value = {
            "jobId": "job-uuid-1",
            "status": "preparing",
            "name": "my-run",
        }
        result = runner.invoke(cli, [
            "train", "start",
            "--name", "my-run",
            "--symbol", "SPY",
        ])
        assert result.exit_code == 0
        assert "job-uuid-1" in result.output
        mock_client.kaggle_train.assert_called_once()

    def test_start_requires_name(self, runner, mock_client):
        result = runner.invoke(cli, ["train", "start", "--symbol", "SPY"])
        assert result.exit_code != 0
        assert "Missing option" in result.output

    def test_start_requires_symbol(self, runner, mock_client):
        result = runner.invoke(cli, ["train", "start", "--name", "test"])
        assert result.exit_code != 0

    def test_start_outputs_json(self, runner, mock_client):
        mock_client.kaggle_train.return_value = {
            "jobId": "j-1", "status": "preparing", "name": "test"
        }
        result = runner.invoke(cli, [
            "train", "start", "--name", "test", "--symbol", "SPY", "--output", "json"
        ])
        assert result.exit_code == 0
        assert '"jobId"' in result.output

    def test_start_exits_1_on_api_error(self, runner, mock_client):
        mock_client.kaggle_train.side_effect = APIError(500, "Internal error")
        result = runner.invoke(cli, [
            "train", "start", "--name", "test", "--symbol", "SPY"
        ])
        assert result.exit_code == 1


class TestTrainListCommand:
    def test_list_shows_table(self, runner, mock_client):
        mock_client.kaggle_list_jobs.return_value = [
            {"id": "j-1", "name": "run-1", "status": "completed",
             "approval_status": "approved", "created_at": "2024-01-01"},
        ]
        result = runner.invoke(cli, ["train", "list"])
        assert result.exit_code == 0
        assert "run-1" in result.output

    def test_list_empty_shows_no_results(self, runner, mock_client):
        mock_client.kaggle_list_jobs.return_value = []
        result = runner.invoke(cli, ["train", "list"])
        assert result.exit_code == 0

    def test_list_pending_approval_flag(self, runner, mock_client):
        mock_client.kaggle_list_jobs.return_value = []
        result = runner.invoke(cli, ["train", "list", "--pending-approval"])
        assert result.exit_code == 0
        mock_client.kaggle_list_jobs.assert_called_with(
            status="pending_approval", approval_status="pending"
        )


class TestTrainStatusCommand:
    def test_shows_job_details(self, runner, mock_client):
        mock_client.kaggle_get_job.return_value = {
            "id": "j-1", "name": "my-run", "status": "training_on_kaggle",
            "approval_status": "pending", "error": None,
        }
        result = runner.invoke(cli, ["train", "status", "j-1"])
        assert result.exit_code == 0
        assert "training_on_kaggle" in result.output

    def test_returns_404_message(self, runner, mock_client):
        mock_client.kaggle_get_job.side_effect = APIError(404, "Job not found")
        result = runner.invoke(cli, ["train", "status", "no-such"])
        assert result.exit_code == 1


class TestTrainCancelCommand:
    def test_cancels_job(self, runner, mock_client):
        mock_client.kaggle_cancel_job.return_value = {"jobId": "j-1", "status": "cancelled"}
        result = runner.invoke(cli, ["train", "cancel", "j-1"])
        assert result.exit_code == 0
        mock_client.kaggle_cancel_job.assert_called_with("j-1")


class TestTrainQuotaCommand:
    def test_shows_quota(self, runner, mock_client):
        mock_client.kaggle_quota.return_value = {
            "username": "testuser",
            "gpuQuota": 30, "gpuUsed": 5, "gpuRemaining": 25,
        }
        result = runner.invoke(cli, ["train", "quota"])
        assert result.exit_code == 0
        assert "25" in result.output


# ─── policy commands ──────────────────────────────────────────────────────────

class TestPolicyListCommand:
    def test_list_shows_policies(self, runner, mock_client):
        mock_client.policy_list.return_value = [
            {"id": "p-1", "name": "my-policy", "version": "1.0",
             "promoted": False, "approval_status": "pending", "created_at": "2024-01-01"},
        ]
        result = runner.invoke(cli, ["policy", "list"])
        assert result.exit_code == 0
        assert "my-policy" in result.output

    def test_list_promoted_flag(self, runner, mock_client):
        mock_client.policy_list.return_value = []
        result = runner.invoke(cli, ["policy", "list", "--promoted"])
        assert result.exit_code == 0
        mock_client.policy_list.assert_called_with(
            promoted_only=True, approval_status=None
        )


class TestPolicyApproveCommand:
    def test_approves_policy(self, runner, mock_client):
        mock_client.policy_approve.return_value = {
            "policyId": "p-1", "approvalStatus": "approved", "approvedBy": "alice"
        }
        result = runner.invoke(cli, ["policy", "approve", "p-1", "--by", "alice"])
        assert result.exit_code == 0
        assert "approved" in result.output.lower()
        mock_client.policy_approve.assert_called_with("p-1", approved_by="alice")

    def test_approve_api_error(self, runner, mock_client):
        mock_client.policy_approve.side_effect = APIError(404, "Policy not found")
        result = runner.invoke(cli, ["policy", "approve", "no-such"])
        assert result.exit_code == 1


class TestPolicyRejectCommand:
    def test_rejects_with_reason(self, runner, mock_client):
        mock_client.policy_reject.return_value = {
            "policyId": "p-1", "approvalStatus": "rejected", "reason": "low sharpe"
        }
        result = runner.invoke(cli, ["policy", "reject", "p-1", "--reason", "low sharpe"])
        assert result.exit_code == 0
        mock_client.policy_reject.assert_called_with("p-1", reason="low sharpe")


class TestPolicyPromoteCommand:
    def test_promotes_policy(self, runner, mock_client):
        mock_client.policy_promote.return_value = {
            "policyId": "p-1", "promoted": True, "promotedBy": "admin"
        }
        result = runner.invoke(cli, ["policy", "promote", "p-1"])
        assert result.exit_code == 0
        assert "promoted" in result.output.lower()


class TestPolicyDownloadCommand:
    def test_downloads_policy(self, runner, mock_client, tmp_path):
        mock_client.policy_download.return_value = b"PK\x03\x04fake-zip-content"
        out_file = str(tmp_path / "model.zip")
        result = runner.invoke(cli, ["policy", "download", "p-1", "--output", out_file])
        assert result.exit_code == 0
        with open(out_file, "rb") as f:
            assert f.read() == b"PK\x03\x04fake-zip-content"

    def test_download_requires_output_flag(self, runner, mock_client):
        result = runner.invoke(cli, ["policy", "download", "p-1"])
        assert result.exit_code != 0

    def test_download_exits_on_non_bytes_response(self, runner, mock_client):
        mock_client.policy_download.return_value = {"error": "not a file"}
        result = runner.invoke(cli, [
            "policy", "download", "p-1", "--output", "/tmp/model.zip"
        ])
        assert result.exit_code == 1


class TestPolicyDeleteCommand:
    def test_deletes_with_yes_flag(self, runner, mock_client):
        mock_client.policy_delete.return_value = None
        result = runner.invoke(cli, ["policy", "delete", "p-1", "--yes"])
        assert result.exit_code == 0
        mock_client.policy_delete.assert_called_with("p-1")

    def test_prompts_without_yes_flag(self, runner, mock_client):
        mock_client.policy_delete.return_value = None
        result = runner.invoke(cli, ["policy", "delete", "p-1"], input="y\n")
        assert result.exit_code == 0

    def test_aborts_on_no_confirmation(self, runner, mock_client):
        result = runner.invoke(cli, ["policy", "delete", "p-1"], input="n\n")
        assert result.exit_code != 0
        mock_client.policy_delete.assert_not_called()


# ─── backtest commands ────────────────────────────────────────────────────────

class TestBacktestRunCommand:
    def test_submits_backtest(self, runner, mock_client):
        mock_client.backtest_run.return_value = {
            "reportId": "r-1", "status": "running"
        }
        result = runner.invoke(cli, [
            "backtest", "run",
            "--name", "test-bt",
            "--symbol", "SPY",
        ])
        assert result.exit_code == 0
        assert "r-1" in result.output

    def test_run_requires_name(self, runner, mock_client):
        result = runner.invoke(cli, ["backtest", "run", "--symbol", "SPY"])
        assert result.exit_code != 0

    def test_run_requires_symbol(self, runner, mock_client):
        result = runner.invoke(cli, ["backtest", "run", "--name", "test"])
        assert result.exit_code != 0


class TestBacktestShowCommand:
    def test_shows_metrics(self, runner, mock_client):
        mock_client.backtest_get.return_value = {
            "id": "r-1", "status": "completed",
            "metrics": {"avgSharpe": 1.5, "avgTotalReturn": 0.12,
                        "avgMaxDrawdown": 0.08, "avgWinRate": 0.55},
        }
        result = runner.invoke(cli, ["backtest", "show", "r-1"])
        assert result.exit_code == 0
        assert "completed" in result.output

    def test_show_api_error(self, runner, mock_client):
        mock_client.backtest_get.side_effect = APIError(404, "Not found")
        result = runner.invoke(cli, ["backtest", "show", "no-such"])
        assert result.exit_code == 1


class TestBacktestListCommand:
    def test_lists_backtests(self, runner, mock_client):
        mock_client.backtest_list.return_value = [
            {"id": "r-1", "name": "bt-1", "status": "completed", "created_at": "2024-01-01"},
        ]
        result = runner.invoke(cli, ["backtest", "list"])
        assert result.exit_code == 0
        assert "bt-1" in result.output


# ─── dataset commands ─────────────────────────────────────────────────────────

class TestDatasetListCommand:
    def test_lists_datasets(self, runner, mock_client):
        mock_client.dataset_list.return_value = [
            {"id": "d-1", "name": "my-dataset", "symbols": ["SPY"],
             "start_date": "2020-01-01", "end_date": "2024-12-31",
             "n_splits": 5, "created_at": "2024-01-01"},
        ]
        result = runner.invoke(cli, ["dataset", "list"])
        assert result.exit_code == 0
        assert "my-dataset" in result.output


class TestDatasetPreviewCommand:
    def test_shows_preview(self, runner, mock_client):
        mock_client.dataset_preview.return_value = {
            "symbols": ["SPY"], "startDate": "2024-01-01", "endDate": "2024-12-31",
            "totalRows": 100, "previewRows": 10, "columns": ["time", "close"],
            "data": [{"time": "2024-01-01", "close": 400.0}] * 10,
        }
        result = runner.invoke(cli, ["dataset", "preview", "--symbol", "SPY"])
        assert result.exit_code == 0

    def test_requires_symbol(self, runner, mock_client):
        result = runner.invoke(cli, ["dataset", "preview"])
        assert result.exit_code != 0


class TestDatasetExportCommand:
    def test_exports_csv(self, runner, mock_client, tmp_path):
        mock_client.dataset_export.return_value = b"time,close\n2024-01-01,400.0\n"
        out_file = str(tmp_path / "data.csv")
        result = runner.invoke(cli, [
            "dataset", "export",
            "--symbol", "SPY", "--format", "csv", "--output", out_file
        ])
        assert result.exit_code == 0
        with open(out_file, "rb") as f:
            assert b"time,close" in f.read()

    def test_export_requires_output(self, runner, mock_client):
        result = runner.invoke(cli, ["dataset", "export", "--symbol", "SPY"])
        assert result.exit_code != 0


class TestDatasetDeleteCommand:
    def test_deletes_with_yes_flag(self, runner, mock_client):
        mock_client.dataset_delete.return_value = None
        result = runner.invoke(cli, ["dataset", "delete", "d-1", "--yes"])
        assert result.exit_code == 0
        mock_client.dataset_delete.assert_called_with("d-1")


# ─── system commands ──────────────────────────────────────────────────────────

class TestSystemStatusCommand:
    def test_shows_status(self, runner, mock_client):
        mock_client.system_overview.return_value = {
            "systemStatus": "healthy",
            "checkedAt": "2024-01-01T00:00:00",
            "services": [{"service": "backtest", "status": "ok", "latencyMs": 10}],
            "stats": {"totalTrainingJobs": 5, "promotedPolicies": 2},
            "pendingApprovals": 1,
            "activeJobs": 0,
        }
        result = runner.invoke(cli, ["system", "status"])
        assert result.exit_code == 0
        assert "healthy" in result.output.lower()

    def test_api_error_exits_1(self, runner, mock_client):
        mock_client.system_overview.side_effect = APIError(503, "Dashboard unavailable")
        result = runner.invoke(cli, ["system", "status"])
        assert result.exit_code == 1


class TestSystemServicesCommand:
    def test_lists_services(self, runner, mock_client):
        mock_client.system_services.return_value = {
            "services": [
                {"service": "kaggle-orchestrator", "status": "ok", "latencyMs": 5},
                {"service": "backtest", "status": "unreachable", "latencyMs": None},
            ],
            "checkedAt": "2024-01-01T00:00:00",
        }
        result = runner.invoke(cli, ["system", "services"])
        assert result.exit_code == 0
        assert "kaggle-orchestrator" in result.output


class TestSystemActivityCommand:
    def test_shows_activity(self, runner, mock_client):
        mock_client.system_activity.return_value = {
            "events": [
                {"type": "training_job", "name": "run-1", "status": "completed",
                 "subStatus": "approved", "timestamp": "2024-06-01"},
            ],
            "generatedAt": "2024-06-01T12:00:00",
        }
        result = runner.invoke(cli, ["system", "activity"])
        assert result.exit_code == 0
        assert "run-1" in result.output


# ─── Global CLI tests ─────────────────────────────────────────────────────────

class TestCLIGlobal:
    def test_help_shows_commands(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        for cmd in ("train", "policy", "backtest", "dataset", "system"):
            assert cmd in result.output

    def test_version_flag(self, runner):
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_subcommand_help(self, runner):
        for cmd in ("train", "policy", "backtest", "dataset", "system"):
            result = runner.invoke(cli, [cmd, "--help"])
            assert result.exit_code == 0
