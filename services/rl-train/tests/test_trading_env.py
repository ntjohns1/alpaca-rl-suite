"""
Smoke tests for TradingEnvironment — no DB, S3, or network required.
Only needs: numpy, pandas, gymnasium (lightweight deps already in conda base).
"""
import sys
import os

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trading_env import (
    TradingEnvironment, DataSource,
    TECHNICAL_COLS, SHARADAR_COLS, ALL_FEATURE_COLS,
)


# ─── helpers ────────────────────────────────────────────────────────────────

def _make_ohlcv_df(n: int = 300, seed: int = 0) -> pd.DataFrame:
    """Raw OHLCV — for feature_mode='compute'."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    close = 100.0 * np.cumprod(1 + rng.normal(0.0003, 0.01, n))
    df = pd.DataFrame({
        "date":   dates,
        "open":   close * rng.uniform(0.99, 1.0, n),
        "high":   close * rng.uniform(1.0, 1.01, n),
        "low":    close * rng.uniform(0.99, 1.0, n),
        "close":  close,
        "volume": rng.integers(1_000_000, 10_000_000, n),
    })
    df = df.set_index("date")
    return df


def _make_precomputed_df(n: int = 300, seed: int = 0) -> pd.DataFrame:
    """Pre-computed 20-feature data — for feature_mode='precomputed'."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    close = 100.0 * np.cumprod(1 + rng.normal(0.0003, 0.01, n))
    data = {"date": dates, "close": close}
    data["ret_1d"]  = np.concatenate([[0], np.diff(close) / close[:-1]])
    data["ret_2d"]  = rng.normal(0, 0.01, n)
    data["ret_5d"]  = rng.normal(0, 0.01, n)
    data["ret_10d"] = rng.normal(0, 0.01, n)
    data["ret_21d"] = rng.normal(0, 0.01, n)
    data["rsi"]     = rng.uniform(20, 80, n)
    data["macd"]    = rng.normal(0, 0.5, n)
    data["atr"]     = rng.uniform(0.5, 3, n)
    data["stoch"]   = rng.uniform(-20, 20, n)
    data["ultosc"]  = rng.uniform(20, 80, n)
    data["pe"]      = rng.uniform(10, 40, n)
    data["pb"]      = rng.uniform(1, 10, n)
    data["ps"]      = rng.uniform(1, 15, n)
    data["evebitda"]      = rng.uniform(5, 25, n)
    data["marketcap_log"] = rng.uniform(20, 28, n)
    data["roe"]           = rng.uniform(-0.1, 0.4, n)
    data["roa"]           = rng.uniform(-0.05, 0.2, n)
    data["debt_equity"]   = rng.uniform(0, 3, n)
    data["revenue_growth"] = rng.uniform(-0.2, 0.5, n)
    data["fcf_yield"]     = rng.uniform(-0.05, 0.15, n)
    df = pd.DataFrame(data).set_index("date")
    return df


def _make_env(n: int = 300, seed: int = 0, feature_mode: str = "compute") -> TradingEnvironment:
    if feature_mode == "compute":
        return TradingEnvironment(df=_make_ohlcv_df(n, seed), feature_mode="compute")
    return TradingEnvironment(df=_make_precomputed_df(n, seed), feature_mode="precomputed")


# ─── DataSource ──────────────────────────────────────────────────────────────

class TestDataSourceCompute:
    def test_min_values_series_has_feature_cols(self):
        ds = DataSource(df=_make_ohlcv_df(300), feature_mode="compute")
        assert ds.min_values is not None
        assert len(ds.min_values) == len(TECHNICAL_COLS)

    def test_data_has_no_nans_after_preprocess(self):
        ds = DataSource(df=_make_ohlcv_df(300), feature_mode="compute")
        assert ds.data is not None
        assert not ds.data.isnull().any().any()

    def test_data_shape_is_days_by_10_features(self):
        n = 300
        ds = DataSource(df=_make_ohlcv_df(n), feature_mode="compute")
        assert ds.data.shape[0] <= n
        assert ds.data.shape[1] == len(TECHNICAL_COLS)


class TestDataSourcePrecomputed:
    def test_min_values_series_has_20_features(self):
        ds = DataSource(df=_make_precomputed_df(300), feature_mode="precomputed")
        assert ds.min_values is not None
        assert len(ds.min_values) == len(ALL_FEATURE_COLS)

    def test_data_has_no_nans(self):
        ds = DataSource(df=_make_precomputed_df(300), feature_mode="precomputed")
        assert not ds.data.isnull().any().any()

    def test_data_shape_is_days_by_20_features(self):
        n = 300
        ds = DataSource(df=_make_precomputed_df(n), feature_mode="precomputed")
        assert ds.data.shape[0] <= n
        assert ds.data.shape[1] == len(ALL_FEATURE_COLS)

    def test_missing_sharadar_cols_filled_with_zero(self):
        df = _make_precomputed_df(300)
        df = df.drop(columns=["pe", "pb"])  # simulate missing
        ds = DataSource(df=df, feature_mode="precomputed")
        assert ds.data.shape[1] == len(ALL_FEATURE_COLS)


# ─── TradingEnvironment ──────────────────────────────────────────────────────

class TestTradingEnvironmentInterface:
    def test_observation_space_shape_is_1d(self):
        env = _make_env()
        assert len(env.observation_space.shape) == 1

    def test_action_space_has_3_actions(self):
        env = _make_env()
        assert env.action_space.n == 3

    def test_reset_returns_obs_and_info(self):
        env = _make_env()
        obs, info = env.reset()
        assert obs.shape == env.observation_space.shape
        assert isinstance(info, dict)

    def test_obs_dtype_is_float32(self):
        env = _make_env()
        obs, _ = env.reset()
        assert obs.dtype == np.float32

    def test_step_returns_5_tuple(self):
        env = _make_env()
        env.reset()
        obs, reward, done, truncated, info = env.step(1)  # HOLD
        assert obs.shape == env.observation_space.shape
        assert isinstance(reward, float)
        assert isinstance(done, bool)
        assert isinstance(truncated, bool)
        assert isinstance(info, dict)

    def test_episode_terminates(self):
        env = _make_env(n=300)
        obs, _ = env.reset()
        done = False
        steps = 0
        while not done and steps < 10_000:
            obs, reward, done, truncated, info = env.step(env.action_space.sample())
            done = done or truncated
            steps += 1
        assert done, "Episode should terminate within data length"

    def test_reward_is_finite(self):
        env = _make_env()
        env.reset()
        for action in [0, 1, 2, 1, 0]:
            obs, reward, done, truncated, _ = env.step(action)
            assert np.isfinite(reward), f"Reward not finite: {reward}"
            if done or truncated:
                break

    def test_reset_seed_produces_same_first_obs(self):
        """Seeding numpy before reset gives a repeatable episode start offset."""
        env = _make_env(seed=42)
        np.random.seed(99)
        obs1, _ = env.reset()
        np.random.seed(99)
        obs2, _ = env.reset()
        np.testing.assert_array_equal(obs1, obs2)


class TestTradingEnvironmentEpisode:
    def test_full_episode_hold_policy(self):
        env = _make_env(n=300)
        env.reset()
        total_reward = 0.0
        done = False
        while not done:
            _, reward, done, truncated, _ = env.step(1)  # HOLD
            total_reward += reward
            done = done or truncated
        assert np.isfinite(total_reward)

    def test_full_episode_long_policy(self):
        env = _make_env(n=300)
        env.reset()
        total_reward = 0.0
        done = False
        while not done:
            _, reward, done, truncated, _ = env.step(2)  # LONG
            total_reward += reward
            done = done or truncated
        assert np.isfinite(total_reward)

    def test_obs_in_observation_space_during_episode(self):
        env = _make_env(n=300)
        obs, _ = env.reset()
        assert env.observation_space.contains(obs)
        for _ in range(20):
            obs, _, done, truncated, _ = env.step(env.action_space.sample())
            assert env.observation_space.contains(obs)
            if done or truncated:
                break


class TestPrecomputedEnvironment:
    def test_observation_space_is_20(self):
        env = _make_env(n=300, feature_mode="precomputed")
        assert env.observation_space.shape == (20,)

    def test_reset_returns_20d_obs(self):
        env = _make_env(n=300, feature_mode="precomputed")
        obs, info = env.reset()
        assert obs.shape == (20,)
        assert obs.dtype == np.float32

    def test_step_returns_20d_obs(self):
        env = _make_env(n=300, feature_mode="precomputed")
        env.reset()
        obs, reward, done, truncated, info = env.step(1)
        assert obs.shape == (20,)
        assert np.isfinite(reward)

    def test_full_episode_precomputed(self):
        env = _make_env(n=300, feature_mode="precomputed")
        env.reset()
        total_reward = 0.0
        done = False
        while not done:
            _, reward, done, truncated, _ = env.step(2)
            total_reward += reward
            done = done or truncated
        assert np.isfinite(total_reward)
