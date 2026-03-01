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

from trading_env import TradingEnvironment, DataSource


# ─── helpers ────────────────────────────────────────────────────────────────

def _make_df(n: int = 300, seed: int = 0) -> pd.DataFrame:
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


def _make_env(n: int = 300, seed: int = 0) -> TradingEnvironment:
    return TradingEnvironment(df=_make_df(n, seed))


# ─── DataSource ──────────────────────────────────────────────────────────────

class TestDataSource:
    def test_min_values_series_has_feature_cols(self):
        ds = DataSource(df=_make_df(300))
        assert ds.min_values is not None
        assert len(ds.min_values) == len(DataSource.FEATURE_COLS)

    def test_data_has_no_nans_after_preprocess(self):
        ds = DataSource(df=_make_df(300))
        assert ds.data is not None
        assert not ds.data.isnull().any().any()

    def test_data_shape_is_days_by_features(self):
        n = 300
        ds = DataSource(df=_make_df(n))
        # rows <= n (NaN-leading rows dropped), cols == 10 features
        assert ds.data.shape[0] <= n
        assert ds.data.shape[1] == len(DataSource.FEATURE_COLS)


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
