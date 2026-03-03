"""
End-to-End Backfill Workflow Tests

Tests the complete backfill pipeline:
1. API request → market-ingest service
2. Data fetch from Alpaca API
3. Database insertion
4. Data validation
"""
import pytest
import requests
import psycopg2
import os
import time
from datetime import datetime, timedelta


BASE_URL = os.getenv("MARKET_INGEST_URL", "http://localhost:3003")
DB_URL = os.getenv("DATABASE_URL", "postgresql://rl_user:rl_pass@localhost:5432/alpaca_rl")


def get_db_connection():
    return psycopg2.connect(DB_URL)


class TestBackfillAPI:
    """Test backfill API endpoints"""
    
    def test_health_endpoint(self):
        """Verify service is running"""
        response = requests.get(f"{BASE_URL}/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
    
    def test_backfill_endpoint_validation(self):
        """Test API validates required fields"""
        # Missing symbols
        response = requests.post(
            f"{BASE_URL}/market/backfill",
            json={
                "timeframe": "1d",
                "startDate": "2024-01-01",
                "endDate": "2024-01-31"
            }
        )
        assert response.status_code == 400
        
        # Invalid timeframe
        response = requests.post(
            f"{BASE_URL}/market/backfill",
            json={
                "symbols": ["SPY"],
                "timeframe": "5m",  # Not supported
                "startDate": "2024-01-01",
                "endDate": "2024-01-31"
            }
        )
        assert response.status_code == 400
    
    def test_backfill_endpoint_accepts_valid_request(self):
        """Test API accepts valid backfill request"""
        response = requests.post(
            f"{BASE_URL}/market/backfill",
            json={
                "symbols": ["SPY"],
                "timeframe": "1d",
                "startDate": "2024-01-01",
                "endDate": "2024-01-31"
            }
        )
        assert response.status_code == 202  # Accepted
        data = response.json()
        assert "jobId" in data
        assert data.get("status") == "accepted"


class TestBackfillE2E:
    """End-to-end backfill tests"""
    
    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clean up test data before and after each test"""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Delete test data
                cur.execute("DELETE FROM bar_1d WHERE symbol = 'TEST'")
                cur.execute("DELETE FROM bar_1m WHERE symbol = 'TEST'")
            conn.commit()
        
        yield
        
        # Cleanup after test
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM bar_1d WHERE symbol = 'TEST'")
                cur.execute("DELETE FROM bar_1m WHERE symbol = 'TEST'")
            conn.commit()
    
    def test_daily_backfill_e2e(self):
        """
        Test complete daily backfill workflow:
        1. Trigger backfill via API
        2. Wait for completion
        3. Verify data in database
        """
        # Use SPY for a real test (small date range)
        start_date = "2024-01-02"
        end_date = "2024-01-05"
        
        # Trigger backfill
        response = requests.post(
            f"{BASE_URL}/market/backfill",
            json={
                "symbols": ["SPY"],
                "timeframe": "1d",
                "startDate": start_date,
                "endDate": end_date
            }
        )
        assert response.status_code == 202
        job_id = response.json()["jobId"]
        
        # Wait for job to complete (max 10 seconds)
        time.sleep(5)
        
        # Verify data was inserted
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*), MIN(time), MAX(time)
                    FROM bar_1d
                    WHERE symbol = 'SPY'
                    AND time >= %s::date
                    AND time <= %s::date
                """, (start_date, end_date))
                
                count, min_time, max_time = cur.fetchone()
                
                # Should have at least 1 bar (markets might be closed some days)
                assert count >= 1, f"Expected at least 1 bar, got {count}"
                assert min_time is not None
                assert max_time is not None
    
    def test_bar_data_integrity(self):
        """Test that inserted bar data has valid values"""
        # Trigger small backfill
        response = requests.post(
            f"{BASE_URL}/market/backfill",
            json={
                "symbols": ["SPY"],
                "timeframe": "1d",
                "startDate": "2024-01-02",
                "endDate": "2024-01-05"
            }
        )
        assert response.status_code == 202
        
        time.sleep(5)
        
        # Check data integrity
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT time, symbol, open, high, low, close, volume, vwap, trade_count
                    FROM bar_1d
                    WHERE symbol = 'SPY'
                    AND time >= '2024-01-02'::date
                    AND time <= '2024-01-05'::date
                    ORDER BY time
                """)
                
                rows = cur.fetchall()
                assert len(rows) >= 1
                
                for row in rows:
                    time_val, symbol, open_val, high, low, close, volume, vwap, trade_count = row
                    
                    # Basic sanity checks
                    assert symbol == "SPY"
                    assert open_val > 0, "Open price should be positive"
                    assert high >= open_val, "High should be >= open"
                    assert high >= close, "High should be >= close"
                    assert low <= open_val, "Low should be <= open"
                    assert low <= close, "Low should be <= close"
                    assert volume > 0, "Volume should be positive"
                    
                    # VWAP should be between low and high
                    if vwap is not None:
                        assert low <= vwap <= high, f"VWAP {vwap} should be between low {low} and high {high}"
    
    def test_duplicate_prevention(self):
        """Test that re-running backfill doesn't create duplicates (upsert)"""
        backfill_request = {
            "symbols": ["SPY"],
            "timeframe": "1d",
            "startDate": "2024-01-02",
            "endDate": "2024-01-03"
        }
        
        # First backfill
        response1 = requests.post(f"{BASE_URL}/market/backfill", json=backfill_request)
        assert response1.status_code == 202
        time.sleep(5)
        
        # Count bars
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) FROM bar_1d
                    WHERE symbol = 'SPY'
                    AND time >= '2024-01-02'::date
                    AND time <= '2024-01-03'::date
                """)
                count1 = cur.fetchone()[0]
        
        # Second backfill (same data)
        response2 = requests.post(f"{BASE_URL}/market/backfill", json=backfill_request)
        assert response2.status_code == 202
        time.sleep(5)
        
        # Count should be the same (upsert, not insert)
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) FROM bar_1d
                    WHERE symbol = 'SPY'
                    AND time >= '2024-01-02'::date
                    AND time <= '2024-01-03'::date
                """)
                count2 = cur.fetchone()[0]
        
        assert count1 == count2, "Duplicate backfill should not create duplicate rows"


class TestBackfillColumnMapping:
    """Test that Alpaca API response maps correctly to database columns"""
    
    def test_column_names_match(self):
        """
        Critical test: Verify backfillJob.ts maps Alpaca data to correct column names.
        This catches the trade_count vs tradeCount issue.
        """
        # Trigger backfill
        response = requests.post(
            f"{BASE_URL}/market/backfill",
            json={
                "symbols": ["SPY"],
                "timeframe": "1d",
                "startDate": "2024-01-02",
                "endDate": "2024-01-02"
            }
        )
        assert response.status_code == 202
        time.sleep(5)
        
        # Query using the exact column names from the schema
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # This query will fail if column names don't match
                cur.execute("""
                    SELECT 
                        time,
                        symbol,
                        open,
                        high,
                        low,
                        close,
                        volume,
                        vwap,
                        trade_count  -- NOT tradeCount!
                    FROM bar_1d
                    WHERE symbol = 'SPY'
                    AND time = '2024-01-02'::date
                """)
                
                row = cur.fetchone()
                assert row is not None, "No data found - backfill may have failed"
                
                # Verify trade_count is populated (if available from Alpaca)
                trade_count = row[8]
                # trade_count can be None for some data sources, but column should exist
                assert trade_count is None or trade_count > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
