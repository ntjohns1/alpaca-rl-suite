"""
Tests for kaggle-orchestrator helper functions:
- upload_model_to_minio
- kagglehub-based functions (upload_dataset_to_kaggle, list_kaggle_datasets, download_model_via_kagglehub)
"""
import os
import sys
from unittest.mock import MagicMock, patch


os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


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


class TestUploadDatasetToKaggle:
    def test_uploads_via_kagglehub(self, monkeypatch, tmp_path):
        monkeypatch.setattr("main.KAGGLE_USERNAME", "testuser")
        csv_path = str(tmp_path / "data.csv")
        with open(csv_path, "w") as f:
            f.write("date,close\n2024-01-01,400.0\n")

        with patch("kagglehub.dataset_upload") as mock_upload:
            from main import upload_dataset_to_kaggle
            result = upload_dataset_to_kaggle(["SPY"], csv_path, "alpaca-rl-spy")

        assert result["dataset_slug"] == "alpaca-rl-spy"
        assert result["status"] == "success"
        assert "testuser/alpaca-rl-spy" in result["url"]
        mock_upload.assert_called_once()
        # Verify handle is correct
        call_args = mock_upload.call_args
        assert call_args[0][0] == "testuser/alpaca-rl-spy"

    def test_preserves_original_csv(self, monkeypatch, tmp_path):
        """The original CSV should not be deleted (copy, not move)."""
        monkeypatch.setattr("main.KAGGLE_USERNAME", "testuser")
        csv_path = str(tmp_path / "data.csv")
        with open(csv_path, "w") as f:
            f.write("date,close\n2024-01-01,400.0\n")

        with patch("kagglehub.dataset_upload"):
            from main import upload_dataset_to_kaggle
            upload_dataset_to_kaggle(["SPY"], csv_path, "alpaca-rl-spy")

        assert os.path.exists(csv_path), "Original CSV should still exist"


class TestListKaggleDatasets:
    def test_returns_formatted_list(self, monkeypatch):
        monkeypatch.setattr("main.KAGGLE_USERNAME", "testuser")
        monkeypatch.setattr("main.KAGGLE_KEY", "tok-123")

        raw_response = [
            {
                "id": 9625101,
                "ref": "testuser/my-dataset",
                "title": "My Dataset",
                "url": "https://www.kaggle.com/datasets/testuser/my-dataset",
                "totalBytes": 41001,
                "lastUpdated": "2026-03-04T01:32:40.017Z",
                "currentVersionNumber": 1,
                "isPrivate": True,
                "downloadCount": 0,
            }
        ]
        with patch("main.kaggle_request", return_value=raw_response):
            from main import list_kaggle_datasets
            result = list_kaggle_datasets()

        assert len(result) == 1
        assert result[0]["id"] == 9625101
        assert result[0]["slug"] == "my-dataset"
        assert result[0]["title"] == "My Dataset"

    def test_handles_empty_list(self, monkeypatch):
        monkeypatch.setattr("main.KAGGLE_USERNAME", "testuser")
        monkeypatch.setattr("main.KAGGLE_KEY", "tok-123")

        with patch("main.kaggle_request", return_value=[]):
            from main import list_kaggle_datasets
            result = list_kaggle_datasets()
        assert result == []


class TestDownloadModelViaKagglehub:
    def test_downloads_via_kagglehub(self, monkeypatch, tmp_path):
        monkeypatch.setattr("main.KAGGLE_USERNAME", "testuser")

        with patch("kagglehub.notebook_output_download",
                   return_value=str(tmp_path)) as mock_dl:
            from main import download_model_via_kagglehub
            result = download_model_via_kagglehub("alpaca-rl-training", str(tmp_path))

        assert result == str(tmp_path)
        mock_dl.assert_called_once_with(
            "testuser/alpaca-rl-training",
            output_dir=str(tmp_path),
        )
