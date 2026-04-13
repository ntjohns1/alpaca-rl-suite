"""
Targeted tests for orchestrate_kaggle_training and complete_kaggle_training
to push coverage over 80%.
"""
import os
import sys
from unittest.mock import MagicMock, patch


os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mock_conn():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = lambda s: s
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_conn.__enter__ = lambda s: s
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor


BASE_CONFIG = {
    "name": "test-job",
    "symbols": ["SPY"],
    "kernelSlug": "alpaca-rl-training",
    "datasetSlug": "alpaca-rl-spy",
    "totalTimesteps": 10000,
}


# ─── orchestrate_kaggle_training ─────────────────────────────────────────────

class TestOrchestrateKaggleTraining:

    def _run(self, config=None, extra_patches=None):
        cfg = config or BASE_CONFIG.copy()
        mock_conn, mock_cursor = _mock_conn()
        mock_cursor.fetchone.return_value = ("policy-uuid-1",)

        job_row_active = {
            "id": "job-1", "status": "training_on_kaggle", "approval_status": "pending",
            "config": cfg, "metadata": None,
        }

        with patch("main.update_kaggle_job") as mock_update, \
             patch("main.export_training_dataset", return_value={"rows": 400, "symbol": "SPY"}), \
             patch("main.create_kaggle_dataset", return_value={"slug": "alpaca-rl-spy"}), \
             patch("main.push_kaggle_kernel", return_value={
                 "kernel_url": "https://kaggle.com/kernels/alpaca-rl-training"
             }), \
             patch("main.get_kernel_status", return_value="complete"), \
             patch("main.get_job_row", return_value=job_row_active), \
             patch("main.download_model_from_kaggle"), \
             patch("main.upload_model_to_minio", return_value="models/kaggle/job-1/policy_best.zip"), \
             patch("main.trigger_backtest_for_job"), \
             patch("main.get_conn", return_value=mock_conn), \
             patch("os.unlink"), \
             patch("os.listdir", return_value=["policy_best.zip"]), \
             patch("tempfile.NamedTemporaryFile") as mock_tmp, \
             patch("tempfile.TemporaryDirectory") as mock_tmpdir, \
             patch("time.sleep"):

            mock_tmp.return_value.__enter__ = lambda s: s
            mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
            mock_tmp.return_value.name = "/tmp/data.csv"

            mock_tmpdir.return_value.__enter__ = lambda s: "/tmp/model_dir"
            mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)

            from main import orchestrate_kaggle_training
            orchestrate_kaggle_training("job-1", cfg)

        return mock_update

    def test_full_happy_path_reaches_pending_approval(self):
        mock_update = self._run()
        statuses = [c[0][1] for c in mock_update.call_args_list]
        assert "pending_approval" in statuses

    def test_triggers_backtest_after_upload(self):
        mock_conn, mock_cursor = _mock_conn()
        mock_cursor.fetchone.return_value = ("pol-1",)
        job_row_active = {"id": "job-1", "status": "training_on_kaggle", "approval_status": "pending", "config": BASE_CONFIG, "metadata": None}

        with patch("main.update_kaggle_job"), \
             patch("main.export_training_dataset", return_value={"rows": 400}), \
             patch("main.create_kaggle_dataset", return_value={}), \
             patch("main.push_kaggle_kernel", return_value={"kernel_url": "https://kaggle.com/k"}), \
             patch("main.get_kernel_status", return_value="complete"), \
             patch("main.get_job_row", return_value=job_row_active), \
             patch("main.download_model_from_kaggle"), \
             patch("main.upload_model_to_minio", return_value="s3://path"), \
             patch("main.trigger_backtest_for_job") as mock_bt, \
             patch("main.get_conn", return_value=mock_conn), \
             patch("os.unlink"), \
             patch("os.listdir", return_value=["policy_best.zip"]), \
             patch("tempfile.NamedTemporaryFile") as mock_tmp, \
             patch("tempfile.TemporaryDirectory") as mock_tmpdir, \
             patch("time.sleep"):
            mock_tmp.return_value.__enter__ = lambda s: s
            mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
            mock_tmp.return_value.name = "/tmp/data.csv"
            mock_tmpdir.return_value.__enter__ = lambda s: "/tmp/dir"
            mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)
            from main import orchestrate_kaggle_training
            orchestrate_kaggle_training("job-1", BASE_CONFIG.copy())
        mock_bt.assert_called_once()

    def test_marks_failed_on_export_error(self):
        with patch("main.update_kaggle_job") as mock_update, \
             patch("main.export_training_dataset", side_effect=RuntimeError("DB down")), \
             patch("main.get_conn"), \
             patch("os.unlink", side_effect=FileNotFoundError), \
             patch("tempfile.NamedTemporaryFile") as mock_tmp:
            mock_tmp.return_value.__enter__ = lambda s: s
            mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
            mock_tmp.return_value.name = "/tmp/data.csv"
            from main import orchestrate_kaggle_training
            orchestrate_kaggle_training("job-1", BASE_CONFIG.copy())
        statuses = [c[0][1] for c in mock_update.call_args_list]
        assert "failed" in statuses

    def test_stops_polling_when_job_cancelled(self):
        cancelled_row = {"id": "job-1", "status": "cancelled", "approval_status": "pending", "config": BASE_CONFIG, "metadata": None}
        with patch("main.update_kaggle_job") as mock_update, \
             patch("main.export_training_dataset", return_value={"rows": 400}), \
             patch("main.create_kaggle_dataset", return_value={}), \
             patch("main.push_kaggle_kernel", return_value={"kernel_url": "https://kaggle.com/k"}), \
             patch("main.get_kernel_status", return_value="running"), \
             patch("main.get_job_row", return_value=cancelled_row), \
             patch("main.get_conn"), \
             patch("os.unlink"), \
             patch("tempfile.NamedTemporaryFile") as mock_tmp, \
             patch("time.sleep"):
            mock_tmp.return_value.__enter__ = lambda s: s
            mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
            mock_tmp.return_value.name = "/tmp/data.csv"
            from main import orchestrate_kaggle_training
            orchestrate_kaggle_training("job-1", BASE_CONFIG.copy())
        statuses = [c[0][1] for c in mock_update.call_args_list]
        assert "failed" not in statuses

    def test_marks_failed_on_kernel_error(self):
        job_row_active = {"id": "job-1", "status": "training_on_kaggle", "approval_status": "pending", "config": BASE_CONFIG, "metadata": None}
        with patch("main.update_kaggle_job") as mock_update, \
             patch("main.export_training_dataset", return_value={"rows": 400}), \
             patch("main.create_kaggle_dataset", return_value={}), \
             patch("main.push_kaggle_kernel", return_value={"kernel_url": "https://kaggle.com/k"}), \
             patch("main.get_kernel_status", return_value="error"), \
             patch("main.get_job_row", return_value=job_row_active), \
             patch("main.get_conn"), \
             patch("os.unlink"), \
             patch("tempfile.NamedTemporaryFile") as mock_tmp, \
             patch("time.sleep"):
            mock_tmp.return_value.__enter__ = lambda s: s
            mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
            mock_tmp.return_value.name = "/tmp/data.csv"
            from main import orchestrate_kaggle_training
            orchestrate_kaggle_training("job-1", BASE_CONFIG.copy())
        statuses = [c[0][1] for c in mock_update.call_args_list]
        assert "failed" in statuses

    def test_marks_failed_when_no_zip_found(self):
        job_row_active = {"id": "job-1", "status": "training_on_kaggle", "approval_status": "pending", "config": BASE_CONFIG, "metadata": None}
        with patch("main.update_kaggle_job") as mock_update, \
             patch("main.export_training_dataset", return_value={"rows": 400}), \
             patch("main.create_kaggle_dataset", return_value={}), \
             patch("main.push_kaggle_kernel", return_value={"kernel_url": "https://kaggle.com/k"}), \
             patch("main.get_kernel_status", return_value="complete"), \
             patch("main.get_job_row", return_value=job_row_active), \
             patch("main.download_model_from_kaggle"), \
             patch("main.get_conn"), \
             patch("os.unlink"), \
             patch("os.listdir", return_value=[]),  \
             patch("tempfile.NamedTemporaryFile") as mock_tmp, \
             patch("tempfile.TemporaryDirectory") as mock_tmpdir, \
             patch("time.sleep"):
            mock_tmp.return_value.__enter__ = lambda s: s
            mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
            mock_tmp.return_value.name = "/tmp/data.csv"
            mock_tmpdir.return_value.__enter__ = lambda s: "/tmp/dir"
            mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)
            from main import orchestrate_kaggle_training
            orchestrate_kaggle_training("job-1", BASE_CONFIG.copy())
        statuses = [c[0][1] for c in mock_update.call_args_list]
        assert "failed" in statuses


# ─── complete_kaggle_training ─────────────────────────────────────────────────

class TestCompleteKaggleTraining:

    def test_happy_path_reaches_pending_approval(self):
        with patch("main.update_kaggle_job") as mock_update, \
             patch("main.download_model_from_kaggle"), \
             patch("main.upload_model_to_minio", return_value="s3://path/model.zip"), \
             patch("os.listdir", return_value=["policy_best.zip"]), \
             patch("tempfile.TemporaryDirectory") as mock_tmpdir:
            mock_tmpdir.return_value.__enter__ = lambda s: "/tmp/dir"
            mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)
            from main import complete_kaggle_training
            complete_kaggle_training("job-1", "alpaca-rl-training")
        statuses = [c[0][1] for c in mock_update.call_args_list]
        assert "downloading_model" in statuses
        assert "pending_approval" in statuses

    def test_marks_failed_when_no_model_file(self):
        with patch("main.update_kaggle_job") as mock_update, \
             patch("main.download_model_from_kaggle"), \
             patch("os.listdir", return_value=[]), \
             patch("tempfile.TemporaryDirectory") as mock_tmpdir:
            mock_tmpdir.return_value.__enter__ = lambda s: "/tmp/dir"
            mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)
            from main import complete_kaggle_training
            complete_kaggle_training("job-1", "alpaca-rl-training")
        statuses = [c[0][1] for c in mock_update.call_args_list]
        assert "failed" in statuses

    def test_marks_failed_on_download_error(self):
        with patch("main.update_kaggle_job") as mock_update, \
             patch("main.download_model_from_kaggle", side_effect=RuntimeError("Kaggle error")), \
             patch("tempfile.TemporaryDirectory") as mock_tmpdir:
            mock_tmpdir.return_value.__enter__ = lambda s: "/tmp/dir"
            mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)
            from main import complete_kaggle_training
            complete_kaggle_training("job-1", "alpaca-rl-training")
        statuses = [c[0][1] for c in mock_update.call_args_list]
        assert "failed" in statuses


# ─── create_kaggle_dataset / push_kaggle_kernel helpers ──────────────────────

class TestCreateKaggleDataset:
    def test_calls_subprocess_run(self, monkeypatch, tmp_path):
        monkeypatch.setattr("main.KAGGLE_USERNAME", "testuser")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Dataset created"
        mock_result.stderr = ""
        # Create a real csv file to copy
        csv_path = str(tmp_path / "data.csv")
        with open(csv_path, "w") as f:
            f.write("date,close\n2024-01-01,400.0\n")
        with patch("subprocess.run", return_value=mock_result) as mock_sub:
            from main import create_kaggle_dataset
            result = create_kaggle_dataset("SPY", csv_path, "alpaca-rl-spy")
        assert mock_sub.called
        assert result["dataset_slug"] == "alpaca-rl-spy"
        assert result["status"] == "success"

    def test_handles_already_exists_by_versioning(self, monkeypatch, tmp_path):
        monkeypatch.setattr("main.KAGGLE_USERNAME", "testuser")
        csv_path = str(tmp_path / "data.csv")
        with open(csv_path, "w") as f:
            f.write("date,close\n2024-01-01,400.0\n")
        create_result = MagicMock(returncode=1, stderr="Dataset already exists", stdout="")
        version_result = MagicMock(returncode=0, stderr="", stdout="Version created")
        with patch("subprocess.run", side_effect=[create_result, version_result]) as mock_sub:
            from main import create_kaggle_dataset
            result = create_kaggle_dataset("SPY", csv_path, "alpaca-rl-spy")
        assert mock_sub.call_count == 2
        assert result["status"] == "success"


class TestPushKaggleKernel:
    def test_calls_subprocess_run(self, monkeypatch, tmp_path):
        monkeypatch.setattr("main.KAGGLE_USERNAME", "testuser")
        mock_result = MagicMock(returncode=0, stdout="Kernel pushed", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_sub, \
             patch("tempfile.gettempdir", return_value=str(tmp_path)):
            from main import push_kaggle_kernel
            result = push_kaggle_kernel("alpaca-rl-training", "alpaca-rl-spy")
        assert mock_sub.called
        assert "kernel_url" in result
        assert result["status"] == "triggered"

    def test_returns_kernel_url_on_nonzero_exit(self, monkeypatch, tmp_path):
        monkeypatch.setattr("main.KAGGLE_USERNAME", "testuser")
        mock_result = MagicMock(returncode=1, stdout="", stderr="some warning")
        with patch("subprocess.run", return_value=mock_result), \
             patch("tempfile.gettempdir", return_value=str(tmp_path)):
            from main import push_kaggle_kernel
            result = push_kaggle_kernel("alpaca-rl-training", "alpaca-rl-spy")
        assert result["status"] == "triggered"
