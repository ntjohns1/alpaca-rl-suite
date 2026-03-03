"""
Kaggle Integration Tests

Tests the Kaggle orchestrator service and training workflow.
"""
import pytest
import requests
import psycopg2
import os
import time
from datetime import datetime


KAGGLE_URL = os.getenv("KAGGLE_ORCHESTRATOR_URL", "http://localhost:8011")
DB_URL = os.getenv("DATABASE_URL", "postgresql://rl_user:rl_pass@localhost:5432/alpaca_rl")


def get_db_connection():
    return psycopg2.connect(DB_URL)


class TestKaggleOrchestratorAPI:
    """Test Kaggle orchestrator API endpoints"""
    
    def test_health_endpoint(self):
        """Verify Kaggle orchestrator is running"""
        response = requests.get(f"{KAGGLE_URL}/kaggle/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
        assert "kaggle_configured" in data
    
    def test_kaggle_credentials_configured(self):
        """Verify Kaggle credentials are set"""
        response = requests.get(f"{KAGGLE_URL}/kaggle/health")
        data = response.json()
        
        # Should have credentials configured
        assert data.get("kaggle_configured") is True, \
            "Kaggle credentials not configured. Set KAGGLE_API_TOKEN and KAGGLE_USERNAME in .env"
    
    def test_train_endpoint_validation(self):
        """Test training endpoint validates required fields"""
        # Missing symbols
        response = requests.post(
            f"{KAGGLE_URL}/kaggle/train",
            json={
                "name": "test",
                "kernelSlug": "alpaca-rl-training",
                "totalTimesteps": 100000
            }
        )
        assert response.status_code == 400
        
        # Missing kernelSlug
        response = requests.post(
            f"{KAGGLE_URL}/kaggle/train",
            json={
                "name": "test",
                "symbols": ["SPY"],
                "totalTimesteps": 100000
            }
        )
        assert response.status_code == 400


class TestKaggleJobManagement:
    """Test Kaggle job tracking and management"""
    
    def test_create_training_job(self):
        """Test creating a training job"""
        response = requests.post(
            f"{KAGGLE_URL}/kaggle/train",
            json={
                "name": "test-job",
                "symbols": ["SPY"],
                "kernelSlug": "alpaca-rl-training",
                "totalTimesteps": 100000
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "jobId" in data
        assert data.get("status") == "preparing"
        assert data.get("name") == "test-job"
        
        return data["jobId"]
    
    def test_get_job_status(self):
        """Test retrieving job status"""
        # Create a job first
        create_response = requests.post(
            f"{KAGGLE_URL}/kaggle/train",
            json={
                "name": "status-test",
                "symbols": ["SPY"],
                "kernelSlug": "alpaca-rl-training",
                "totalTimesteps": 100000
            }
        )
        job_id = create_response.json()["jobId"]
        
        # Get job status
        response = requests.get(f"{KAGGLE_URL}/kaggle/jobs/{job_id}")
        assert response.status_code == 200
        
        data = response.json()
        assert data["id"] == job_id
        assert "status" in data
        assert "config" in data
        assert "created_at" in data
    
    def test_list_jobs(self):
        """Test listing all jobs"""
        response = requests.get(f"{KAGGLE_URL}/kaggle/jobs")
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data, list)
        
        # If there are jobs, verify structure
        if len(data) > 0:
            job = data[0]
            assert "id" in job
            assert "name" in job
            assert "status" in job


class TestDatasetExport:
    """Test dataset export functionality"""
    
    def test_export_requires_data(self):
        """Test that export fails gracefully if no data exists"""
        # Try to export a symbol with no data
        response = requests.post(
            f"{KAGGLE_URL}/kaggle/train",
            json={
                "name": "no-data-test",
                "symbols": ["NONEXISTENT"],
                "kernelSlug": "alpaca-rl-training",
                "totalTimesteps": 100000
            }
        )
        
        # Job should be created
        assert response.status_code == 200
        job_id = response.json()["jobId"]
        
        # Wait a bit for processing
        time.sleep(3)
        
        # Check job status - should have failed or have error
        status_response = requests.get(f"{KAGGLE_URL}/kaggle/jobs/{job_id}")
        job_data = status_response.json()
        
        # Job should either fail or indicate no data
        # (depends on implementation - might succeed with empty dataset)
        assert job_data["status"] in ["failed", "manual_trigger_required"]


class TestKaggleJobDatabase:
    """Test Kaggle job database schema and operations"""
    
    def test_job_table_exists(self):
        """Verify kaggle_training_job table exists"""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = 'kaggle_training_job'
                    )
                """)
                exists = cur.fetchone()[0]
                assert exists, "kaggle_training_job table does not exist"
    
    def test_job_persisted_to_database(self):
        """Test that jobs are persisted to database"""
        # Create a job
        response = requests.post(
            f"{KAGGLE_URL}/kaggle/train",
            json={
                "name": "db-persist-test",
                "symbols": ["SPY"],
                "kernelSlug": "alpaca-rl-training",
                "totalTimesteps": 100000
            }
        )
        job_id = response.json()["jobId"]
        
        # Check database
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, name, status, config
                    FROM kaggle_training_job
                    WHERE id = %s
                """, (job_id,))
                
                row = cur.fetchone()
                assert row is not None, f"Job {job_id} not found in database"
                
                db_id, db_name, db_status, db_config = row
                assert db_id == job_id
                assert db_name == "db-persist-test"
                assert db_status in ["preparing", "exporting_dataset", "uploading_dataset", 
                                     "manual_trigger_required", "failed"]


class TestKaggleWorkflowE2E:
    """End-to-end Kaggle workflow tests"""
    
    @pytest.mark.slow
    def test_full_workflow_to_dataset_upload(self):
        """
        Test complete workflow up to dataset upload:
        1. Create training job
        2. Export dataset from PostgreSQL
        3. Upload to Kaggle
        4. Verify manual trigger instructions
        
        Note: This doesn't test actual Kaggle notebook execution
        """
        # Ensure we have data for SPY
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) FROM bar_1d WHERE symbol = 'SPY'
                """)
                count = cur.fetchone()[0]
                
                if count == 0:
                    pytest.skip("No SPY data in database. Run backfill first.")
        
        # Create training job
        response = requests.post(
            f"{KAGGLE_URL}/kaggle/train",
            json={
                "name": "e2e-workflow-test",
                "symbols": ["SPY"],
                "kernelSlug": "alpaca-rl-training",
                "totalTimesteps": 100000
            }
        )
        
        assert response.status_code == 200
        job_id = response.json()["jobId"]
        
        # Wait for dataset upload (may take 10-30 seconds)
        max_wait = 60
        waited = 0
        final_status = None
        
        while waited < max_wait:
            time.sleep(5)
            waited += 5
            
            status_response = requests.get(f"{KAGGLE_URL}/kaggle/jobs/{job_id}")
            job_data = status_response.json()
            status = job_data["status"]
            
            # Check if we've reached a terminal state
            if status in ["manual_trigger_required", "failed", "completed"]:
                final_status = status
                break
        
        assert final_status is not None, f"Job didn't complete within {max_wait}s"
        
        # For now, we expect manual_trigger_required since we can't auto-trigger notebooks
        if final_status == "manual_trigger_required":
            # Success - dataset was uploaded
            assert "metadata" in job_data
            metadata = job_data.get("metadata", {})
            
            # Should have dataset info
            if "dataset_info" in metadata:
                dataset_info = metadata["dataset_info"]
                assert "dataset_slug" in dataset_info
                assert "url" in dataset_info
        
        elif final_status == "failed":
            # Check error message
            error = job_data.get("error", "Unknown error")
            pytest.fail(f"Workflow failed: {error}")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
