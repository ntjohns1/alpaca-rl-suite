"""
Targeted tests for run_backtest_task and fetch_features_for_backtest
to push coverage over 80%.
"""
import json
import os
import sys
from unittest.mock import MagicMock, patch, call

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_features(n=60, symbol="SPY"):
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "time":   pd.date_range("2022-01-01", periods=n, freq="B"),
        "symbol": symbol,
        "ret_1d":  rng.normal(0, 0.01, n),
        "ret_2d":  rng.normal(0, 0.01, n),
        "ret_5d":  rng.normal(0, 0.01, n),
        "ret_10d": rng.normal(0, 0.01, n),
        "ret_21d": rng.normal(0, 0.01, n),
        "rsi":    rng.uniform(20, 80, n),
        "macd":   rng.normal(0, 0.5, n),
        "atr":    rng.uniform(0.5, 3.0, n),
        "stoch":  rng.uniform(10, 90, n),
        "ultosc": rng.uniform(20, 80, n),
        "close":  100.0 + rng.normal(0, 2, n),
    })


class TestFetchFeaturesForBacktest:
    def test_returns_dataframe(self):
        df = _make_features(30)
        with patch("pandas.read_sql", return_value=df), \
             patch("main.get_conn") as mock_gc:
            mock_gc.return_value.__enter__ = lambda s: s
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)
            from main import fetch_features_for_backtest
            result = fetch_features_for_backtest(["SPY"], "2022-01-01", "2022-12-31")
        assert len(result) == 30

    def test_passes_symbols_and_dates(self):
        df = _make_features(10)
        with patch("pandas.read_sql", return_value=df) as mock_sql, \
             patch("main.get_conn") as mock_gc:
            mock_gc.return_value.__enter__ = lambda s: s
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)
            from main import fetch_features_for_backtest
            fetch_features_for_backtest(["SPY", "AAPL"], "2022-01-01", "2022-12-31")
        sql_called = mock_sql.call_args[0][0]
        assert "%s" in sql_called


class TestRunBacktestTask:
    def _mock_conn(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        return mock_conn, mock_cursor

    def test_marks_failed_when_no_data(self):
        with patch("main.get_conn") as mock_gc, \
             patch("main.fetch_features_for_backtest", return_value=pd.DataFrame()), \
             patch("main.update_backtest_record") as mock_upd:
            mock_conn, mock_cursor = self._mock_conn()
            mock_gc.return_value = mock_conn
            from main import run_backtest_task
            run_backtest_task("r-1", {
                "symbols": ["SPY"],
                "startDate": "2022-01-01",
                "endDate": "2022-12-31",
            })
        mock_upd.assert_called_with("r-1", "failed", {}, error="No data found")

    def test_marks_failed_when_insufficient_per_symbol(self):
        tiny_df = _make_features(5)  # < 22 rows
        with patch("main.fetch_features_for_backtest", return_value=tiny_df), \
             patch("main.update_backtest_record") as mock_upd, \
             patch("main.get_conn") as mock_gc:
            mock_conn, _ = self._mock_conn()
            mock_gc.return_value = mock_conn
            from main import run_backtest_task
            run_backtest_task("r-2", {
                "symbols": ["SPY"],
                "startDate": "2022-01-01",
                "endDate": "2022-12-31",
            })
        mock_upd.assert_called_with("r-2", "failed", {}, error="Insufficient data for all symbols")

    def test_completes_successfully_with_good_data(self):
        df = _make_features(60)
        mock_s3 = MagicMock()
        with patch("main.fetch_features_for_backtest", return_value=df), \
             patch("main.update_backtest_record") as mock_upd, \
             patch("main.generate_charts", return_value={}), \
             patch("main.upload_charts_to_s3", return_value={}), \
             patch("main.get_s3", return_value=mock_s3), \
             patch("main.get_conn") as mock_gc:
            mock_conn, _ = self._mock_conn()
            mock_gc.return_value = mock_conn
            from main import run_backtest_task
            run_backtest_task("r-3", {
                "symbols": ["SPY"],
                "startDate": "2022-01-01",
                "endDate": "2022-12-31",
            })
        # Final call should be "completed"
        final_call = mock_upd.call_args
        assert final_call[0][1] == "completed"
        assert mock_s3.put_object.called

    def test_uses_buy_and_hold_when_no_policy_id(self):
        df = _make_features(60)
        mock_s3 = MagicMock()
        with patch("main.fetch_features_for_backtest", return_value=df), \
             patch("main.update_backtest_record"), \
             patch("main.generate_charts", return_value={}), \
             patch("main.upload_charts_to_s3", return_value={}), \
             patch("main.get_s3", return_value=mock_s3), \
             patch("main.buy_and_hold_policy") as mock_bah, \
             patch("main.get_conn") as mock_gc:
            mock_conn, _ = self._mock_conn()
            mock_gc.return_value = mock_conn
            from main import run_backtest_task
            run_backtest_task("r-4", {
                "symbols": ["SPY"],
                "startDate": "2022-01-01",
                "endDate": "2022-12-31",
            })

    def test_loads_policy_from_s3_when_policy_id_provided(self):
        df = _make_features(60)
        policy_row = pd.DataFrame([{"s3_path": "models/run-1/policy.zip"}])
        mock_s3 = MagicMock()
        fake_policy = MagicMock(return_value=1)
        with patch("main.fetch_features_for_backtest", return_value=df), \
             patch("main.update_backtest_record"), \
             patch("main.generate_charts", return_value={}), \
             patch("main.upload_charts_to_s3", return_value={}), \
             patch("main.get_s3", return_value=mock_s3), \
             patch("main.load_policy_from_s3", return_value=fake_policy), \
             patch("pandas.read_sql", return_value=policy_row), \
             patch("main.get_conn") as mock_gc:
            mock_conn, _ = self._mock_conn()
            mock_gc.return_value = mock_conn
            from main import run_backtest_task
            run_backtest_task("r-5", {
                "symbols": ["SPY"],
                "startDate": "2022-01-01",
                "endDate": "2022-12-31",
                "policyId": "pol-1",
            })

    def test_marks_failed_on_exception(self):
        with patch("main.fetch_features_for_backtest", side_effect=RuntimeError("DB down")), \
             patch("main.update_backtest_record") as mock_upd, \
             patch("main.get_conn") as mock_gc:
            mock_conn, _ = self._mock_conn()
            mock_gc.return_value = mock_conn
            from main import run_backtest_task
            run_backtest_task("r-6", {
                "symbols": ["SPY"],
                "startDate": "2022-01-01",
                "endDate": "2022-12-31",
            })
        mock_upd.assert_called_with("r-6", "failed", {}, error="DB down")

    def test_aggregates_metrics_across_symbols(self):
        spy_df = _make_features(60, "SPY")
        aapl_df = _make_features(60, "AAPL")
        combined = pd.concat([spy_df, aapl_df], ignore_index=True)
        mock_s3 = MagicMock()
        captured_metrics = {}

        def capture_update(rid, status, metrics, **kwargs):
            if status == "completed":
                captured_metrics.update(metrics)

        with patch("main.fetch_features_for_backtest", return_value=combined), \
             patch("main.update_backtest_record", side_effect=capture_update), \
             patch("main.generate_charts", return_value={}), \
             patch("main.upload_charts_to_s3", return_value={}), \
             patch("main.get_s3", return_value=mock_s3), \
             patch("main.get_conn") as mock_gc:
            mock_conn, _ = self._mock_conn()
            mock_gc.return_value = mock_conn
            from main import run_backtest_task
            run_backtest_task("r-7", {
                "symbols": ["SPY", "AAPL"],
                "startDate": "2022-01-01",
                "endDate": "2022-12-31",
            })
        assert "avgSharpe" in captured_metrics
        assert len(captured_metrics["perSymbol"]) == 2
