"""
Unit tests for BacktestEngine — no DB, S3, or network required.
"""
import sys
import os
import math

import pandas as pd
import numpy as np

# Make the service importable without installed deps
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine import BacktestEngine, buy_and_hold_policy, random_policy


# ─── helpers ────────────────────────────────────────────────────────────────

def _make_df(n: int = 252, seed: int = 42) -> pd.DataFrame:
    """Build a synthetic feature DataFrame matching BacktestEngine expectations."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    close = 100.0 * np.cumprod(1 + rng.normal(0.0003, 0.01, n))
    log_rets = np.log(close[1:] / close[:-1])
    log_rets = np.concatenate([[0.0], log_rets])

    df = pd.DataFrame({
        "time":    dates,
        "close":   close,
        "ret_1d":  log_rets,
        "ret_2d":  np.roll(log_rets, 1),
        "ret_5d":  np.roll(log_rets, 4),
        "ret_10d": np.roll(log_rets, 9),
        "ret_21d": np.roll(log_rets, 20),
        "rsi":     rng.uniform(20, 80, n),
        "macd":    rng.normal(0, 0.5, n),
        "atr":     rng.uniform(0.5, 3.0, n),
        "stoch":   rng.uniform(10, 90, n),
        "ultosc":  rng.uniform(20, 80, n),
    })
    return df


# ─── tests ──────────────────────────────────────────────────────────────────

class TestBacktestEngineBasics:
    def test_returns_expected_keys(self):
        df = _make_df(100)
        engine = BacktestEngine()
        result = engine.run(df, buy_and_hold_policy)
        for key in [
            "finalNav", "initialCapital", "totalReturn", "annualizedReturn",
            "marketReturn", "sharpeRatio", "sortinoRatio", "maxDrawdown",
            "winRate", "profitFactor", "totalTrades", "tradingDays", "equityCurve",
        ]:
            assert key in result, f"Missing key: {key}"

    def test_equity_curve_length_matches_input(self):
        n = 150
        df = _make_df(n)
        engine = BacktestEngine()
        result = engine.run(df, buy_and_hold_policy)
        assert len(result["equityCurve"]) == n

    def test_initial_capital_preserved_in_output(self):
        engine = BacktestEngine(initial_capital=50_000)
        result = engine.run(_make_df(50), buy_and_hold_policy)
        assert result["initialCapital"] == 50_000

    def test_hold_policy_has_zero_trades(self):
        def hold_policy(_state): return 1  # always HOLD
        engine = BacktestEngine()
        result = engine.run(_make_df(100), hold_policy)
        assert result["totalTrades"] == 0

    def test_buy_and_hold_nav_changes(self):
        engine = BacktestEngine()
        result = engine.run(_make_df(100), buy_and_hold_policy)
        # NAV should not stay exactly at initial capital
        assert result["finalNav"] != result["initialCapital"]

    def test_trading_days_matches_rows(self):
        df = _make_df(200)
        engine = BacktestEngine()
        result = engine.run(df, buy_and_hold_policy)
        assert result["tradingDays"] == 200


class TestCostModel:
    def test_trading_cost_reduces_nav_vs_zero_cost(self):
        df = _make_df(100, seed=1)
        # Full-cost engine
        engine_cost = BacktestEngine(trading_cost_bps=10, time_cost_bps=1)
        # Zero-cost engine
        engine_free = BacktestEngine(trading_cost_bps=0, time_cost_bps=0)
        # Use a policy that switches positions frequently
        def switch_policy(_): return int(np.random.randint(0, 3))
        np.random.seed(7)
        r_cost = engine_cost.run(df, switch_policy)
        np.random.seed(7)
        r_free = engine_free.run(df, switch_policy)
        # Zero-cost run should end with higher or equal NAV
        assert r_free["finalNav"] >= r_cost["finalNav"]

    def test_equity_curve_contains_cost_field(self):
        df = _make_df(50)
        engine = BacktestEngine()
        result = engine.run(df, buy_and_hold_policy)
        assert "cost" in result["equityCurve"][0]


class TestMetricsCalculation:
    def test_max_drawdown_is_non_negative(self):
        df = _make_df(252)
        engine = BacktestEngine()
        result = engine.run(df, buy_and_hold_policy)
        assert result["maxDrawdown"] >= 0.0

    def test_max_drawdown_is_at_most_1(self):
        df = _make_df(252)
        engine = BacktestEngine()
        result = engine.run(df, buy_and_hold_policy)
        assert result["maxDrawdown"] <= 1.0

    def test_win_rate_between_0_and_1(self):
        df = _make_df(252)
        engine = BacktestEngine()
        result = engine.run(df, buy_and_hold_policy)
        assert 0.0 <= result["winRate"] <= 1.0

    def test_total_return_formula(self):
        df = _make_df(100)
        engine = BacktestEngine(initial_capital=100_000)
        result = engine.run(df, buy_and_hold_policy)
        expected = (result["finalNav"] - 100_000) / 100_000
        assert abs(result["totalReturn"] - expected) < 1e-4

    def test_sharpe_is_finite(self):
        df = _make_df(252)
        engine = BacktestEngine()
        result = engine.run(df, buy_and_hold_policy)
        assert math.isfinite(result["sharpeRatio"])


class TestBiasGuards:
    def test_no_lookahead_on_hold_policy(self):
        """
        A HOLD policy should produce exactly market returns scaled by 0 position.
        nav should barely change (only time_cost_bps per bar).
        """
        df = _make_df(100)
        engine = BacktestEngine(trading_cost_bps=10, time_cost_bps=0)
        def hold_policy(_): return 1  # HOLD → position=0
        result = engine.run(df, hold_policy)
        # All strategy returns should be ≤ 0 (only cost, no position)
        for bar in result["equityCurve"]:
            assert bar["strategy_ret"] <= 1e-9, (
                f"HOLD with 0 position should not gain: {bar['strategy_ret']}"
            )

    def test_empty_dataframe_returns_empty_metrics(self):
        df = pd.DataFrame(columns=[
            "time","close","ret_1d","ret_2d","ret_5d","ret_10d","ret_21d",
            "rsi","macd","atr","stoch","ultosc",
        ])
        engine = BacktestEngine()
        result = engine.run(df, buy_and_hold_policy)
        assert result == {}

    def test_deterministic_with_seed(self):
        """Same seed → identical results."""
        df = _make_df(100)
        r1 = BacktestEngine(seed=42).run(df, random_policy)
        r2 = BacktestEngine(seed=42).run(df, random_policy)
        assert r1["finalNav"] == r2["finalNav"]
        assert r1["totalTrades"] == r2["totalTrades"]
