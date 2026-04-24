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

from engine import BacktestEngine, buy_and_hold_policy


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

    def test_equity_curve_length_is_n_minus_1(self):
        """N input rows produce N-1 return-generating bars (terminal close excluded)."""
        n = 150
        df = _make_df(n)
        engine = BacktestEngine()
        result = engine.run(df, buy_and_hold_policy)
        assert len(result["equityCurve"]) == n - 1

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

    def test_trading_days_is_n_minus_1(self):
        df = _make_df(200)
        engine = BacktestEngine()
        result = engine.run(df, buy_and_hold_policy)
        assert result["tradingDays"] == 199


class TestCostModel:
    def test_trading_cost_reduces_nav_vs_zero_cost(self):
        df = _make_df(100, seed=1)
        engine_cost = BacktestEngine(trading_cost_bps=10, time_cost_bps=1, seed=7)
        engine_free = BacktestEngine(trading_cost_bps=0, time_cost_bps=0, seed=7)
        r_cost = engine_cost.run(df, engine_cost.make_random_policy())
        r_free = engine_free.run(df, engine_free.make_random_policy())
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
        e1 = BacktestEngine(seed=42)
        e2 = BacktestEngine(seed=42)
        r1 = e1.run(df, e1.make_random_policy())
        r2 = e2.run(df, e2.make_random_policy())
        assert r1["finalNav"] == r2["finalNav"]
        assert r1["totalTrades"] == r2["totalTrades"]

    def test_rng_isolation_between_instances(self):
        """Interleaving two engines must not affect their outputs."""
        df = _make_df(80)
        # Baseline: each engine run to completion sequentially.
        e1a = BacktestEngine(seed=13)
        e2a = BacktestEngine(seed=99)
        r1_seq = e1a.run(df, e1a.make_random_policy())
        r2_seq = e2a.run(df, e2a.make_random_policy())
        # Interleaved: construct both, then run. Global state would leak here
        # if seeds were set via np.random.seed.
        e1b = BacktestEngine(seed=13)
        e2b = BacktestEngine(seed=99)
        p1 = e1b.make_random_policy()
        p2 = e2b.make_random_policy()
        # Run e2 first — if RNGs were global, this would shift e1's stream.
        r2_int = e2b.run(df, p2)
        r1_int = e1b.run(df, p1)
        assert r1_seq["finalNav"] == r1_int["finalNav"]
        assert r2_seq["finalNav"] == r2_int["finalNav"]


class TestCorrectnessFixes:
    def test_no_lookahead_uses_next_bar_return(self):
        """
        Construct a df where current ret_1d perfectly signals current-bar return.
        A policy that 'cheats' by keying on state[0] (ret_1d) must NOT earn
        riskless profit, because the realized return is shifted to next bar.
        """
        n = 50
        # Alternate ±0.02 returns
        rets = np.array([0.02 if i % 2 == 0 else -0.02 for i in range(n)])
        dates = pd.date_range("2021-01-01", periods=n, freq="B")
        df = pd.DataFrame({
            "time":    dates,
            "ret_1d":  rets,
            "ret_2d":  rets, "ret_5d": rets, "ret_10d": rets, "ret_21d": rets,
            "rsi":     50.0, "macd": 0.0, "atr": 1.0, "stoch": 50.0, "ultosc": 50.0,
        })
        # Cheating policy: if current ret_1d > 0 go LONG, else SHORT.
        # With look-ahead, this earns |0.02| every bar. Without, it loses,
        # because signal and realized return are antiphased after shift.
        def cheating_policy(state):
            return 2 if state[0] > 0 else 0
        engine = BacktestEngine(trading_cost_bps=0, time_cost_bps=0)
        result = engine.run(df, cheating_policy)
        # If look-ahead were present, totalReturn would be strongly positive.
        # After the fix, it should be non-positive.
        assert result["totalReturn"] <= 0.0, (
            f"Look-ahead leak: totalReturn={result['totalReturn']}"
        )

    def test_alpha_zero_on_flat_market(self):
        """Buy-and-hold on a zero-return market should produce ~0 alpha."""
        n = 100
        dates = pd.date_range("2021-01-01", periods=n, freq="B")
        df = pd.DataFrame({
            "time":    dates,
            "ret_1d":  np.zeros(n),
            "ret_2d":  np.zeros(n), "ret_5d": np.zeros(n),
            "ret_10d": np.zeros(n), "ret_21d": np.zeros(n),
            "rsi":     50.0, "macd": 0.0, "atr": 1.0, "stoch": 50.0, "ultosc": 50.0,
        })
        engine = BacktestEngine(trading_cost_bps=0, time_cost_bps=0)
        result = engine.run(df, buy_and_hold_policy)
        assert abs(result["alpha"]) < 1e-3

    def test_sortino_is_inf_with_no_losses(self):
        """A policy that never loses should report sortino as inf, not nan."""
        n = 20
        dates = pd.date_range("2021-01-01", periods=n, freq="B")
        df = pd.DataFrame({
            "time":    dates,
            "ret_1d":  np.full(n, 0.01),
            "ret_2d":  np.zeros(n), "ret_5d": np.zeros(n),
            "ret_10d": np.zeros(n), "ret_21d": np.zeros(n),
            "rsi":     50.0, "macd": 0.0, "atr": 1.0, "stoch": 50.0, "ultosc": 50.0,
        })
        engine = BacktestEngine(trading_cost_bps=0, time_cost_bps=0)
        result = engine.run(df, buy_and_hold_policy)
        assert math.isinf(result["sortinoRatio"])
        assert not math.isnan(result["sortinoRatio"])

    def test_nan_features_do_not_leak_to_policy(self):
        """NaN in feature columns should be coerced to 0.0 before policy sees them."""
        df = _make_df(30)
        df.loc[5, "rsi"] = np.nan
        df.loc[10, "macd"] = np.nan
        seen_nan = {"flag": False}
        def watchdog_policy(state):
            if any(math.isnan(x) for x in state):
                seen_nan["flag"] = True
            return 1
        engine = BacktestEngine()
        engine.run(df, watchdog_policy)
        assert not seen_nan["flag"]

    def test_invalid_action_raises(self):
        df = _make_df(10)
        def bad_policy(_): return 3
        engine = BacktestEngine()
        try:
            engine.run(df, bad_policy)
        except ValueError:
            return
        raise AssertionError("expected ValueError for invalid policy output")


class TestTerminalBarAndTradeUnits:
    def test_terminal_bar_incurs_no_cost(self):
        """
        A 2-row df with nonzero time_cost_bps and a HOLD (flat) policy
        must leave NAV at initial capital: only one return period exists,
        and with position=0 it generates no P&L. The terminal row is not
        charged carry cost.
        """
        df = pd.DataFrame({
            "time":    pd.date_range("2024-01-01", periods=2, freq="B"),
            "ret_1d":  [0.0, 0.0],
            "ret_2d":  [0.0, 0.0], "ret_5d": [0.0, 0.0],
            "ret_10d": [0.0, 0.0], "ret_21d": [0.0, 0.0],
            "rsi":     [50.0, 50.0], "macd": [0.0, 0.0], "atr": [1.0, 1.0],
            "stoch":   [50.0, 50.0], "ultosc": [50.0, 50.0],
        })
        engine = BacktestEngine(trading_cost_bps=10, time_cost_bps=100)
        def hold(_): return 1
        result = engine.run(df, hold)
        # One return-generating bar. HOLD from flat → no trade units →
        # time_cost is charged on that single bar, so NAV drops by exactly
        # time_cost_bps. Terminal bar contributes no additional cost.
        assert result["tradingDays"] == 1
        expected_nav = 100_000 * (1 - 100 / 10_000)
        assert abs(result["finalNav"] - expected_nav) < 0.01

    def test_single_row_df_returns_empty(self):
        """A 1-row df cannot form a return period → no metrics."""
        df = pd.DataFrame({
            "time":    [pd.Timestamp("2024-01-01")],
            "ret_1d":  [0.01],
            "ret_2d":  [0.0], "ret_5d": [0.0],
            "ret_10d": [0.0], "ret_21d": [0.0],
            "rsi":     [50.0], "macd": [0.0], "atr": [1.0],
            "stoch":   [50.0], "ultosc": [50.0],
        })
        assert BacktestEngine().run(df, buy_and_hold_policy) == {}

    def test_reversal_charges_two_units_but_counts_one_change(self):
        """
        Short→long flip: totalTradeUnits += 2 (two executions), but
        totalPositionChanges += 1 (one bar with a change).
        """
        n = 4
        df = pd.DataFrame({
            "time":    pd.date_range("2024-01-01", periods=n, freq="B"),
            "ret_1d":  [0.0] * n,
            "ret_2d":  [0.0] * n, "ret_5d": [0.0] * n,
            "ret_10d": [0.0] * n, "ret_21d": [0.0] * n,
            "rsi":     [50.0] * n, "macd": [0.0] * n, "atr": [1.0] * n,
            "stoch":   [50.0] * n, "ultosc": [50.0] * n,
        })
        # Actions: SHORT, LONG, LONG — the SHORT→LONG transition at bar 1
        # is the reversal we care about. Only 3 decisions (N-1 bars).
        calls = {"i": 0}
        def scripted(_):
            seq = [0, 2, 2]  # SHORT, LONG, LONG
            a = seq[calls["i"]]
            calls["i"] += 1
            return a
        engine = BacktestEngine(trading_cost_bps=10, time_cost_bps=0)
        result = engine.run(df, scripted)
        # Bars:
        #   b0: pos 0→-1 (1 unit, 1 change)
        #   b1: pos -1→1 (2 units, 1 change)   ← reversal
        #   b2: pos 1→1  (0 units)
        assert result["totalPositionChanges"] == 2
        assert result["totalTradeUnits"] == 3
        # Backwards-compatible alias still reports position changes.
        assert result["totalTrades"] == result["totalPositionChanges"]

    def test_flat_strategy_sortino_is_zero_not_inf(self):
        """
        A strategy that produces only zero returns (no positions, no carry)
        should NOT report infinite Sortino — that would poison any ranking
        logic. With mean_ret == 0 and no losses, return 0.0.
        """
        n = 30
        df = pd.DataFrame({
            "time":    pd.date_range("2024-01-01", periods=n, freq="B"),
            "ret_1d":  np.zeros(n),
            "ret_2d":  np.zeros(n), "ret_5d": np.zeros(n),
            "ret_10d": np.zeros(n), "ret_21d": np.zeros(n),
            "rsi":     [50.0] * n, "macd": [0.0] * n, "atr": [1.0] * n,
            "stoch":   [50.0] * n, "ultosc": [50.0] * n,
        })
        # HOLD policy keeps position=0 the whole time.
        engine = BacktestEngine(trading_cost_bps=0, time_cost_bps=0)
        def hold(_): return 1
        result = engine.run(df, hold)
        assert result["sortinoRatio"] == 0.0
        assert not math.isinf(result["sortinoRatio"])


class TestPerRunRngReset:
    def test_same_engine_reproducible_across_runs(self):
        """
        With a seed, calling run() twice on the same engine must yield
        identical results — symbol ordering must not perturb per-symbol
        outputs.
        """
        df = _make_df(60)
        engine = BacktestEngine(seed=7)
        p = engine.make_random_policy()
        r1 = engine.run(df, p)
        r2 = engine.run(df, p)
        assert r1["finalNav"] == r2["finalNav"]
        assert r1["totalTradeUnits"] == r2["totalTradeUnits"]

    def test_ordering_invariance_across_symbols(self):
        """
        Running A then B on a seeded engine must give the same A and B
        results as running B then A. This is the real integration guarantee.
        """
        dfA = _make_df(50, seed=1)
        dfB = _make_df(50, seed=2)

        e1 = BacktestEngine(seed=42)
        rA_first  = e1.run(dfA, e1.make_random_policy())
        rB_second = e1.run(dfB, e1.make_random_policy())

        e2 = BacktestEngine(seed=42)
        rB_first  = e2.run(dfB, e2.make_random_policy())
        rA_second = e2.run(dfA, e2.make_random_policy())

        assert rA_first["finalNav"] == rA_second["finalNav"]
        assert rB_first["finalNav"] == rB_second["finalNav"]
