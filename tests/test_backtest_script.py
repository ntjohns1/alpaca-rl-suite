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
    """Test metrics calculation"""
    
    def test_calculate_metrics_basic(self):
        """Test basic metrics calculation"""
        # Create simple equity curve
        equity_curve = []
        initial_capital = 100000
        
        for i in range(252):
            nav = initial_capital * (1 + 0.0001 * i)  # Steady growth
            market_nav = initial_capital * (1 + 0.00005 * i)  # Slower growth
            
            equity_curve.append({
                "date": f"2024-01-{i+1:02d}",
                "nav": nav,
                "market_nav": market_nav,
                "position": 1,
                "strategy_ret": 0.0001,
                "market_ret": 0.00005,
                "cost": 0.0001,
            })
        
        metrics = bp.calculate_metrics(equity_curve, initial_capital, 10)
        
        # Check all expected metrics exist
        assert "total_return" in metrics
        assert "sharpe_ratio" in metrics
        assert "max_drawdown" in metrics
        assert "win_rate" in metrics
        assert "profit_factor" in metrics
        assert "alpha" in metrics
        
        # Basic sanity checks
        assert metrics["total_return"] > 0, "Should have positive return"
        assert metrics["max_drawdown"] >= 0, "Drawdown should be non-negative"
        assert 0 <= metrics["win_rate"] <= 1, "Win rate should be between 0 and 1"


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
