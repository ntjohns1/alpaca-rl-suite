"""
Targeted tests for orchestrate_kaggle_training and complete_kaggle_training
to push coverage over 80%.
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
import requests


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
    """Tests for the simplified orchestration flow: export → upload → push → done."""

    def _run(self, config=None, push_return=None, export_side_effect=None, push_side_effect=None):
        cfg = config or BASE_CONFIG.copy()
        push_ret = push_return or {
            "kernel_url": "https://kaggle.com/code/testuser/alpaca-rl-training",
            "version_number": 3,
        }

        with patch("main.update_kaggle_job") as mock_update, \
             patch("main.export_training_dataset",
                   side_effect=export_side_effect,
                   return_value={"rows": 400, "symbol": "SPY"}) if not export_side_effect else \
             patch("main.export_training_dataset", side_effect=export_side_effect) as _, \
             patch("main.create_kaggle_dataset", return_value={"slug": "alpaca-rl-spy"}), \
             patch("main.push_kaggle_kernel",
                   side_effect=push_side_effect,
                   return_value=push_ret) if not push_side_effect else \
             patch("main.push_kaggle_kernel", side_effect=push_side_effect) as _, \
             patch("os.unlink"), \
             patch("tempfile.NamedTemporaryFile") as mock_tmp:

            mock_tmp.return_value.__enter__ = lambda s: s
            mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
            mock_tmp.return_value.name = "/tmp/data.csv"

            from main import orchestrate_kaggle_training
            orchestrate_kaggle_training("job-1", cfg)

        return mock_update

    def test_happy_path_reaches_submitted_to_kaggle(self):
        """Orchestration ends at submitted_to_kaggle (no polling)."""
        with patch("main.update_kaggle_job") as mock_update, \
             patch("main.export_training_dataset", return_value={"rows": 400, "symbol": "SPY"}), \
             patch("main.create_kaggle_dataset", return_value={"slug": "alpaca-rl-spy"}), \
             patch("main.push_kaggle_kernel", return_value={
                 "kernel_url": "https://kaggle.com/code/testuser/alpaca-rl-training",
                 "version_number": 3,
             }), \
             patch("os.unlink"), \
             patch("tempfile.NamedTemporaryFile") as mock_tmp:
            mock_tmp.return_value.__enter__ = lambda s: s
            mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
            mock_tmp.return_value.name = "/tmp/data.csv"
            from main import orchestrate_kaggle_training
            orchestrate_kaggle_training("job-1", BASE_CONFIG.copy())
        statuses = [c[0][1] for c in mock_update.call_args_list]
        assert "submitted_to_kaggle" in statuses
        # No polling or model download should happen
        assert "training_on_kaggle" not in statuses
        assert "downloading_model" not in statuses

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

    def test_marks_failed_on_push_error(self):
        with patch("main.update_kaggle_job") as mock_update, \
             patch("main.export_training_dataset", return_value={"rows": 400}), \
             patch("main.create_kaggle_dataset", return_value={}), \
             patch("main.push_kaggle_kernel", side_effect=RuntimeError("Kaggle push failed")), \
             patch("os.unlink"), \
             patch("tempfile.NamedTemporaryFile") as mock_tmp:
            mock_tmp.return_value.__enter__ = lambda s: s
            mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
            mock_tmp.return_value.name = "/tmp/data.csv"
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
    def test_creates_dataset_via_api(self, monkeypatch, tmp_path):
        monkeypatch.setattr("main.KAGGLE_USERNAME", "testuser")
        monkeypatch.setattr("main.KAGGLE_API_TOKEN", "tok-123")
        csv_path = str(tmp_path / "data.csv")
        with open(csv_path, "w") as f:
            f.write("date,close\n2024-01-01,400.0\n")

        mock_blob_resp = MagicMock()
        mock_blob_resp.status_code = 200
        mock_blob_resp.raise_for_status = MagicMock()
        mock_blob_resp.json.return_value = {"token": "blob-tok-1", "createUrl": "https://gcs.example/upload"}

        mock_put_resp = MagicMock()
        mock_put_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=mock_blob_resp), \
             patch("requests.put", return_value=mock_put_resp), \
             patch("main.kaggle_request", return_value={"status": "ok"}) as mock_kgr:
            from main import create_kaggle_dataset
            result = create_kaggle_dataset("SPY", csv_path, "alpaca-rl-spy")
        assert result["dataset_slug"] == "alpaca-rl-spy"
        assert result["status"] == "success"
        mock_kgr.assert_called_once()

    def test_handles_already_exists_by_versioning(self, monkeypatch, tmp_path):
        monkeypatch.setattr("main.KAGGLE_USERNAME", "testuser")
        monkeypatch.setattr("main.KAGGLE_API_TOKEN", "tok-123")
        csv_path = str(tmp_path / "data.csv")
        with open(csv_path, "w") as f:
            f.write("date,close\n2024-01-01,400.0\n")

        mock_blob_resp = MagicMock()
        mock_blob_resp.status_code = 200
        mock_blob_resp.raise_for_status = MagicMock()
        mock_blob_resp.json.return_value = {"token": "blob-tok-1", "createUrl": "https://gcs.example/upload"}

        mock_put_resp = MagicMock()
        mock_put_resp.raise_for_status = MagicMock()

        import requests as req_mod
        http_error = req_mod.HTTPError(response=MagicMock(status_code=409))

        calls = []
        def fake_kaggle_request(method, endpoint, **kwargs):
            calls.append((method, endpoint))
            if len(calls) == 1:
                raise http_error
            return {"status": "ok"}

        with patch("requests.post", return_value=mock_blob_resp), \
             patch("requests.put", return_value=mock_put_resp), \
             patch("main.kaggle_request", side_effect=fake_kaggle_request):
            from main import create_kaggle_dataset
            result = create_kaggle_dataset("SPY", csv_path, "alpaca-rl-spy")
        assert len(calls) == 2
        assert calls[0] == ("POST", "/datasets/create/new")
        assert calls[1][0] == "POST"
        assert "/datasets/create/version/" in calls[1][1]
        assert result["status"] == "success"


class TestUploadBlob:
    def test_raises_on_missing_token_in_response(self, monkeypatch, tmp_path):
        monkeypatch.setattr("main.KAGGLE_USERNAME", "testuser")
        monkeypatch.setattr("main.KAGGLE_API_TOKEN", "tok-123")
        csv_path = str(tmp_path / "data.csv")
        with open(csv_path, "w") as f:
            f.write("date,close\n2024-01-01,400.0\n")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"createUrl": "https://gcs.example/upload"}  # no token

        with patch("requests.post", return_value=mock_resp):
            from main import _upload_blob
            with pytest.raises(ValueError, match="missing createUrl or token"):
                _upload_blob(csv_path, "data.csv")

    def test_raises_on_blob_api_error(self, monkeypatch, tmp_path):
        monkeypatch.setattr("main.KAGGLE_USERNAME", "testuser")
        monkeypatch.setattr("main.KAGGLE_API_TOKEN", "tok-123")
        csv_path = str(tmp_path / "data.csv")
        with open(csv_path, "w") as f:
            f.write("date,close\n2024-01-01,400.0\n")

        import requests as req_mod
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"
        mock_resp.raise_for_status.side_effect = req_mod.HTTPError("403")

        with patch("requests.post", return_value=mock_resp):
            from main import _upload_blob
            with pytest.raises(req_mod.HTTPError):
                _upload_blob(csv_path, "data.csv")


class TestPushKaggleKernel:
    def test_pushes_new_kernel_via_api(self, monkeypatch, tmp_path):
        """When _get_kernel_id returns None (kernel doesn't exist), use newTitle/slug."""
        monkeypatch.setattr("main.KAGGLE_USERNAME", "testuser")
        monkeypatch.setattr("main.KAGGLE_API_TOKEN", "tok-123")
        notebook = tmp_path / "notebook.ipynb"
        notebook.write_text('{"cells": []}')
        monkeypatch.setenv("KAGGLE_NOTEBOOK_PATH", str(notebook))

        def mock_request(method, path, **kwargs):
            if "/kernels/pull/" in path:
                # Simulate 404 — kernel doesn't exist yet
                resp = requests.Response()
                resp.status_code = 404
                raise requests.HTTPError(response=resp)
            return {"versionNumber": 1}

        with patch("main.kaggle_request", side_effect=mock_request) as mock_kgr:
            from main import push_kaggle_kernel
            result = push_kaggle_kernel("alpaca-rl-training", "alpaca-rl-spy")
        # Verify the push call used newTitle (not id)
        push_call = [c for c in mock_kgr.call_args_list if c[0] == ("POST", "/kernels/push")]
        assert len(push_call) == 1
        body = push_call[0][1]["json"]
        assert "id" not in body
        assert body["newTitle"] == "Alpaca RL Training"
        assert result["status"] == "triggered"

    def test_pushes_existing_kernel_with_numeric_id(self, monkeypatch, tmp_path):
        """When _get_kernel_id finds the kernel, use numeric id."""
        monkeypatch.setattr("main.KAGGLE_USERNAME", "testuser")
        monkeypatch.setattr("main.KAGGLE_API_TOKEN", "tok-123")
        notebook = tmp_path / "notebook.ipynb"
        notebook.write_text('{"cells": []}')
        monkeypatch.setenv("KAGGLE_NOTEBOOK_PATH", str(notebook))

        def mock_request(method, path, **kwargs):
            if "/kernels/pull/" in path:
                return {"metadata": {"id": 120470939, "ref": "testuser/alpaca-rl-training"}}
            return {"versionNumber": 4}

        with patch("main.kaggle_request", side_effect=mock_request) as mock_kgr:
            from main import push_kaggle_kernel
            result = push_kaggle_kernel("alpaca-rl-training", "alpaca-rl-spy")
        push_call = [c for c in mock_kgr.call_args_list if c[0] == ("POST", "/kernels/push")]
        assert len(push_call) == 1
        body = push_call[0][1]["json"]
        assert body["id"] == 120470939
        assert body["slug"] == "alpaca-rl-training"
        assert "newTitle" not in body
        assert result["version_number"] == 4

    def test_raises_if_notebook_missing(self, monkeypatch):
        monkeypatch.setattr("main.KAGGLE_USERNAME", "testuser")
        monkeypatch.setattr("main.KAGGLE_API_TOKEN", "tok-123")
        monkeypatch.setenv("KAGGLE_NOTEBOOK_PATH", "/nonexistent/path.ipynb")
        from main import push_kaggle_kernel
        import pytest
        with pytest.raises(FileNotFoundError):
            push_kaggle_kernel("alpaca-rl-training", "alpaca-rl-spy")


class TestDownloadModelFromKaggle:
    def test_downloads_files(self, monkeypatch, tmp_path):
        monkeypatch.setattr("main.KAGGLE_USERNAME", "testuser")
        monkeypatch.setattr("main.KAGGLE_API_TOKEN", "tok-123")

        mock_dl = MagicMock()
        mock_dl.raise_for_status = MagicMock()
        mock_dl.iter_content = MagicMock(return_value=[b"model-data"])

        with patch("main.kaggle_request", return_value={
            "files": [{"url": "https://gcs.example/model.zip", "fileName": "policy_best.zip"}]
        }), patch("requests.get", return_value=mock_dl):
            from main import download_model_from_kaggle
            download_model_from_kaggle("alpaca-rl-training", str(tmp_path))

        assert (tmp_path / "policy_best.zip").exists()

    def test_raises_on_no_files(self, monkeypatch):
        monkeypatch.setattr("main.KAGGLE_USERNAME", "testuser")
        monkeypatch.setattr("main.KAGGLE_API_TOKEN", "tok-123")

        with patch("main.kaggle_request", return_value={"files": []}):
            from main import download_model_from_kaggle
            with pytest.raises(ValueError, match="No output files"):
                download_model_from_kaggle("alpaca-rl-training", "/tmp/out")

    def test_raises_when_all_urls_empty(self, monkeypatch, tmp_path):
        monkeypatch.setattr("main.KAGGLE_USERNAME", "testuser")
        monkeypatch.setattr("main.KAGGLE_API_TOKEN", "tok-123")

        with patch("main.kaggle_request", return_value={
            "files": [{"fileName": "model.zip", "url": ""}]
        }):
            from main import download_model_from_kaggle
            with pytest.raises(ValueError, match="lacked download URLs"):
                download_model_from_kaggle("alpaca-rl-training", str(tmp_path))


class TestUploadModelToMinio:
    def test_uploads_to_s3(self, monkeypatch, tmp_path):
        monkeypatch.setattr("main.S3_BUCKET", "test-bucket")
        model_file = tmp_path / "model.zip"
        model_file.write_bytes(b"fake-model")

        mock_s3 = MagicMock()
        with patch("main.get_s3", return_value=mock_s3):
            from main import upload_model_to_minio
            result = upload_model_to_minio(str(model_file), "models/test/model.zip")

        assert result == "s3://test-bucket/models/test/model.zip"
        mock_s3.put_object.assert_called_once()
