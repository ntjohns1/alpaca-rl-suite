"""
Database Schema Validation Tests

Ensures that database schema matches what the application code expects.
Catches issues like column name mismatches (e.g., trade_count vs tradeCount).
"""
import pytest
import psycopg2
import os
from typing import Dict, List, Set


def get_db_connection():
    """Get database connection from environment"""
    db_url = os.getenv(
        "DATABASE_URL",
        "postgresql://rl_user:rl_pass@localhost:5432/alpaca_rl"
    )
    return psycopg2.connect(db_url)


def get_table_columns(conn, table_name: str) -> Dict[str, str]:
    """Get column names and types for a table"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = %s
            ORDER BY ordinal_position
        """, (table_name,))
        return {row[0]: row[1] for row in cur.fetchall()}


class TestBarTableSchema:
    """Test bar_1m and bar_1d table schemas"""
    
    EXPECTED_COLUMNS = {
        'time': 'timestamp with time zone',
        'symbol': 'text',
        'open': 'numeric',
        'high': 'numeric',
        'low': 'numeric',
        'close': 'numeric',
        'volume': 'bigint',
        'vwap': 'numeric',
        'trade_count': 'integer',
    }
    
    def test_bar_1m_schema(self):
        """Validate bar_1m table has correct columns"""
        with get_db_connection() as conn:
            columns = get_table_columns(conn, 'bar_1m')
            
            # Check all expected columns exist
            for col_name, col_type in self.EXPECTED_COLUMNS.items():
                assert col_name in columns, f"Missing column: {col_name}"
                assert columns[col_name] == col_type, \
                    f"Column {col_name} has type {columns[col_name]}, expected {col_type}"
            
            # Check no unexpected columns (except internal ones)
            expected_set = set(self.EXPECTED_COLUMNS.keys())
            actual_set = set(columns.keys())
            unexpected = actual_set - expected_set
            
            # Filter out TimescaleDB internal columns
            unexpected = {c for c in unexpected if not c.startswith('_')}
            assert not unexpected, f"Unexpected columns: {unexpected}"
    
    def test_bar_1d_schema(self):
        """Validate bar_1d table has correct columns"""
        with get_db_connection() as conn:
            columns = get_table_columns(conn, 'bar_1d')
            
            for col_name, col_type in self.EXPECTED_COLUMNS.items():
                assert col_name in columns, f"Missing column: {col_name}"
                assert columns[col_name] == col_type, \
                    f"Column {col_name} has type {columns[col_name]}, expected {col_type}"
    
    def test_bar_indexes(self):
        """Validate required indexes exist"""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Check bar_1m indexes
                cur.execute("""
                    SELECT indexname FROM pg_indexes 
                    WHERE tablename = 'bar_1m'
                """)
                indexes_1m = {row[0] for row in cur.fetchall()}
                assert 'idx_bar_1m_symbol_time' in indexes_1m
                
                # Check bar_1d indexes
                cur.execute("""
                    SELECT indexname FROM pg_indexes 
                    WHERE tablename = 'bar_1d'
                """)
                indexes_1d = {row[0] for row in cur.fetchall()}
                assert 'idx_bar_1d_symbol_time' in indexes_1d


class TestFeatureTableSchema:
    """Test feature_row table schema"""
    
    EXPECTED_COLUMNS = {
        'time': 'timestamp with time zone',
        'symbol': 'text',
        'ret_1d': 'numeric',
        'ret_2d': 'numeric',
        'ret_5d': 'numeric',
        'ret_10d': 'numeric',
        'ret_21d': 'numeric',
        'rsi': 'numeric',
        'macd': 'numeric',
        'atr': 'numeric',
        'stoch': 'numeric',
        'ultosc': 'numeric',
        'parquet_ref': 'text',
    }
    
    def test_feature_row_schema(self):
        """Validate feature_row table has correct columns"""
        with get_db_connection() as conn:
            columns = get_table_columns(conn, 'feature_row')
            
            for col_name, col_type in self.EXPECTED_COLUMNS.items():
                assert col_name in columns, f"Missing column: {col_name}"
                assert columns[col_name] == col_type, \
                    f"Column {col_name} has type {columns[col_name]}, expected {col_type}"


class TestBackfillJobSchema:
    """Test that backfillJob.ts expectations match database schema"""
    
    def test_bar_insert_columns_match(self):
        """
        Validate that the columns used in backfillJob.ts match the database.
        This catches issues like trade_count vs tradeCount.
        """
        with get_db_connection() as conn:
            # Get actual columns from both tables
            bar_1m_cols = set(get_table_columns(conn, 'bar_1m').keys())
            bar_1d_cols = set(get_table_columns(conn, 'bar_1d').keys())
            
            # Columns that backfillJob.ts tries to insert
            # From services/market-ingest/src/backfillJob.ts mapped object
            expected_insert_cols = {
                'time',
                'symbol',
                'open',
                'high',
                'low',
                'close',
                'volume',
                'vwap',
                'trade_count',  # NOT tradeCount!
            }
            
            # Verify all insert columns exist in bar_1m
            missing_1m = expected_insert_cols - bar_1m_cols
            assert not missing_1m, \
                f"bar_1m missing columns that backfillJob tries to insert: {missing_1m}"
            
            # Verify all insert columns exist in bar_1d
            missing_1d = expected_insert_cols - bar_1d_cols
            assert not missing_1d, \
                f"bar_1d missing columns that backfillJob tries to insert: {missing_1d}"
    
    def test_no_camelcase_columns(self):
        """Ensure database uses snake_case, not camelCase"""
        with get_db_connection() as conn:
            for table in ['bar_1m', 'bar_1d', 'feature_row']:
                columns = get_table_columns(conn, table)
                
                # Check for camelCase (has uppercase letter not at start)
                camelcase_cols = [
                    col for col in columns.keys()
                    if any(c.isupper() for c in col[1:])
                ]
                
                assert not camelcase_cols, \
                    f"Table {table} has camelCase columns: {camelcase_cols}. Use snake_case."


class TestTimescaleDB:
    """Test TimescaleDB hypertable configuration"""
    
    def test_hypertables_exist(self):
        """Verify hypertables are created"""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT hypertable_name 
                    FROM timescaledb_information.hypertables
                """)
                hypertables = {row[0] for row in cur.fetchall()}
                
                assert 'bar_1m' in hypertables
                assert 'bar_1d' in hypertables
                assert 'feature_row' in hypertables
    
    def test_hypertable_time_column(self):
        """Verify hypertables use 'time' as the time dimension"""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT hypertable_name, column_name
                    FROM timescaledb_information.dimensions
                """)
                time_columns = {row[0]: row[1] for row in cur.fetchall()}
                
                assert time_columns.get('bar_1m') == 'time'
                assert time_columns.get('bar_1d') == 'time'
                assert time_columns.get('feature_row') == 'time'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
