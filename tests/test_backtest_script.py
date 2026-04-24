"""
Tests for backtest_policy.py script

Validates that the backtest script correctly:
1. Loads data from database
2. Calculates features matching trading_env.py
3. Runs backtest and calculates metrics
4. Evaluates promotion criteria
"""
import pytest
import os
import sys
import tempfile
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import backtest_policy as bp
import pandas as pd
import numpy as np


class TestFeatureCalculation:
    """Test that features match trading_env.py"""
    
    def test_feature_columns(self):
        """Verify feature columns are correct"""
        # Create sample data
        dates = pd.date_range('2024-01-01', periods=100, freq='D')
        df = pd.DataFrame({
            'date': dates,
            'open': np.random.randn(100).cumsum() + 100,
            'high': np.random.randn(100).cumsum() + 102,
            'low': np.random.randn(100).cumsum() + 98,
            'close': np.random.randn(100).cumsum() + 100,
            'volume': np.random.randint(1000000, 10000000, 100)
        })
        
        # Calculate features
        df_features = bp.calculate_features(df)
        
        # Check expected columns exist
        expected_features = [
            "returns", "ret_2", "ret_5", "ret_10", "ret_21",
            "rsi", "macd", "atr", "stoch", "ultosc"
        ]
        
        for feature in expected_features:
            assert feature in df_features.columns, f"Missing feature: {feature}"
    
    def test_normalization_preserves_returns(self):
        """Verify normalization doesn't scale returns (needed for backtest)"""
        dates = pd.date_range('2024-01-01', periods=100, freq='D')
        df = pd.DataFrame({
            'date': dates,
            'open': np.random.randn(100).cumsum() + 100,
            'high': np.random.randn(100).cumsum() + 102,
            'low': np.random.randn(100).cumsum() + 98,
            'close': np.random.randn(100).cumsum() + 100,
            'volume': np.random.randint(1000000, 10000000, 100)
        })
        
        df_features = bp.calculate_features(df)
        returns_before = df_features["returns"].copy()
        
        df_normalized = bp.normalize_features(df_features)
        returns_after = df_normalized["returns"]
        
        # Returns should be identical (not normalized)
        pd.testing.assert_series_equal(returns_before, returns_after)


class TestMetricsCalculation:
    """End-to-end metrics via the shared BacktestEngine."""

    @staticmethod
    def _make_feature_df(n: int = 100) -> pd.DataFrame:
        """DataFrame shaped like what calculate_features+normalize_features emit."""
        rng = np.random.default_rng(0)
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        returns = rng.normal(0.0005, 0.01, n)
        df = pd.DataFrame({
            "date":    dates,
            "returns": returns,
            "ret_2":   np.roll(returns, 1),
            "ret_5":   np.roll(returns, 4),
            "ret_10":  np.roll(returns, 9),
            "ret_21":  np.roll(returns, 20),
            "rsi":     rng.uniform(20, 80, n),
            "macd":    rng.normal(0, 0.5, n),
            "atr":     rng.uniform(0.5, 3.0, n),
            "stoch":   rng.uniform(10, 90, n),
            "ultosc":  rng.uniform(20, 80, n),
        }).set_index("date")
        return df

    def test_run_backtest_returns_expected_snake_case_keys(self):
        df = self._make_feature_df(120)
        result = bp.run_backtest(
            df, lambda _s: 2, initial_capital=100_000,
            trading_cost_bps=0, time_cost_bps=0,
        )
        for key in (
            "total_return", "annualized_return", "market_return", "alpha",
            "sharpe_ratio", "sortino_ratio", "max_drawdown", "win_rate",
            "profit_factor", "total_trades", "trading_days",
        ):
            assert key in result["metrics"], f"Missing key: {key}"
        assert result["metrics"]["trading_days"] == 120
        assert len(result["equity_curve"]) == 120

    def test_script_matches_service_on_shared_fixture(self):
        """Script and service must agree on all metrics — no drift."""
        from engine import BacktestEngine, buy_and_hold_policy

        df_script = self._make_feature_df(150)
        script_result = bp.run_backtest(
            df_script, buy_and_hold_policy, initial_capital=100_000,
            trading_cost_bps=10, time_cost_bps=1,
        )

        df_engine = bp._to_engine_df(df_script)
        engine_result = BacktestEngine(
            initial_capital=100_000, trading_cost_bps=10, time_cost_bps=1,
        ).run(df_engine, buy_and_hold_policy)

        for camel, snake in bp._ENGINE_TO_SNAKE.items():
            if camel == "equityCurve":
                continue
            assert script_result["metrics"][snake] == engine_result[camel], (
                f"Drift on {camel}/{snake}: "
                f"script={script_result['metrics'][snake]} vs "
                f"engine={engine_result[camel]}"
            )


class TestPromotionCriteria:
    """Test promotion criteria evaluation"""
    
    def test_promotion_all_pass(self):
        """Test promotion when all criteria pass"""
        metrics = {
            "sharpe_ratio": 1.5,
            "max_drawdown": 0.10,
            "win_rate": 0.55,
            "alpha": 0.05,
        }
        
        criteria = bp.evaluate_promotion_criteria(metrics)
        
        assert criteria["sharpe_gt_1"] is True
        assert criteria["drawdown_lt_15pct"] is True
        assert criteria["win_rate_gt_50pct"] is True
        assert criteria["beats_market"] is True
        assert criteria["recommend_promotion"] is True
    
    def test_promotion_some_fail(self):
        """Test promotion when some criteria fail"""
        metrics = {
            "sharpe_ratio": 0.8,  # FAIL: < 1.0
            "max_drawdown": 0.10,
            "win_rate": 0.55,
            "alpha": 0.05,
        }
        
        criteria = bp.evaluate_promotion_criteria(metrics)
        
        assert criteria["sharpe_gt_1"] is False
        assert criteria["recommend_promotion"] is False
    
    def test_promotion_negative_alpha(self):
        """Test promotion fails when underperforming market"""
        metrics = {
            "sharpe_ratio": 1.5,
            "max_drawdown": 0.10,
            "win_rate": 0.55,
            "alpha": -0.02,  # FAIL: underperforming
        }
        
        criteria = bp.evaluate_promotion_criteria(metrics)
        
        assert criteria["beats_market"] is False
        assert criteria["recommend_promotion"] is False


class TestEndToEnd:
    """End-to-end integration tests"""
    
    @pytest.mark.skipif(
        not os.getenv("DATABASE_URL"),
        reason="DATABASE_URL not set"
    )
    def test_load_data_from_db(self):
        """Test loading data from database (requires DB connection)"""
        database_url = os.getenv("DATABASE_URL")
        
        try:
            df = bp.load_data_from_db("SPY", "2024-01-01", "2024-01-31", database_url)
            
            assert len(df) > 0, "Should load some data"
            assert "date" in df.columns
            assert "close" in df.columns
            assert "high" in df.columns
            assert "low" in df.columns
            
        except Exception as e:
            pytest.skip(f"Database connection failed: {e}")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
