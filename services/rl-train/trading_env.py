"""
Trading environment for RL training.
Adapted from 22_deep_reinforcement_learning/trading_env.py
Changes: loads from PostgreSQL/parquet instead of assets.h5
"""
import logging
import sys
import os
import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces
from sklearn.preprocessing import scale

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))
from feature_columns import TECHNICAL_COLS, SHARADAR_COLS, ALL_FEATURE_COLS, VALID_FEATURE_MODES

log = logging.getLogger(__name__)


class DataSource:
    """
    Loads & preprocesses daily bar data.
    Supports two modes:
      - "precomputed" (default): expects 20 pre-computed feature columns from feature-builder.
      - "compute": recomputes 10 technical indicators from OHLCV (requires `ta` library).
    """

    FEATURE_COLS = ALL_FEATURE_COLS  # 20 features

    def __init__(self, df: pd.DataFrame, trading_days: int = 252,
                 normalize: bool = True, feature_mode: str = "precomputed"):
        """
        df: DataFrame indexed by date.
            precomputed mode: must contain ret_1d..ultosc + SHARADAR cols + close.
            compute mode: must contain close, high, low columns.
        feature_mode: "precomputed" or "compute"
        """
        if feature_mode not in VALID_FEATURE_MODES:
            raise ValueError(
                f"Invalid feature_mode '{feature_mode}'. "
                f"Must be one of {VALID_FEATURE_MODES}"
            )
        self.trading_days = trading_days
        self.normalize = normalize
        self.feature_mode = feature_mode
        if feature_mode == "compute":
            self._active_cols = TECHNICAL_COLS
        else:
            self._active_cols = ALL_FEATURE_COLS
        self.data = self._preprocess(df)
        self.min_values = self.data.min()
        self.max_values = self.data.max()
        self.step = 0
        self.offset = None

    def _preprocess(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy().sort_index()

        if self.feature_mode == "compute":
            import ta as _ta
            df["ret_1d"]  = df["close"].pct_change()
            df["ret_2d"]  = df["close"].pct_change(2)
            df["ret_5d"]  = df["close"].pct_change(5)
            df["ret_10d"] = df["close"].pct_change(10)
            df["ret_21d"] = df["close"].pct_change(21)
            df["rsi"]     = _ta.momentum.RSIIndicator(df["close"], window=14).rsi()
            macd_obj      = _ta.trend.MACD(df["close"])
            df["macd"]    = macd_obj.macd_signal()
            df["atr"]     = _ta.volatility.AverageTrueRange(
                df["high"], df["low"], df["close"], window=14
            ).average_true_range()
            stoch_obj     = _ta.momentum.StochasticOscillator(
                df["high"], df["low"], df["close"], window=14
            )
            df["stoch"]   = stoch_obj.stoch_signal() - stoch_obj.stoch()
            df["ultosc"]  = _ta.momentum.UltimateOscillator(
                df["high"], df["low"], df["close"]
            ).ultimate_oscillator()
        else:
            # Precomputed mode: replace inf before fillna so inf doesn't survive
            df = df.replace([np.inf, -np.inf], np.nan)
            sharadar_present = [c for c in SHARADAR_COLS if c in df.columns]
            if sharadar_present:
                df[sharadar_present] = df[sharadar_present].fillna(0)
            # Fill any missing feature columns with 0
            for c in self._active_cols:
                if c not in df.columns:
                    log.warning(f"Missing feature column '{c}', filling with 0")
                    df[c] = 0.0

        df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=TECHNICAL_COLS)

        # Store raw ret_1d separately for reward signal, then scale all features
        self._ret_1d = df["ret_1d"].copy()
        if self.normalize:
            df[self._active_cols] = scale(df[self._active_cols])
        return df[self._active_cols]

    def reset(self):
        high = len(self.data) - self.trading_days
        self.offset = np.random.randint(low=0, high=max(high, 1))
        self.step = 0

    def take_step(self):
        idx = self.offset + self.step
        obs = self.data.iloc[idx].values
        market_return = self._ret_1d.iloc[idx]
        self.step += 1
        done = self.step > self.trading_days
        return obs, market_return, done


class TradingSimulator:
    """Tracks NAV, positions, costs. Mirrors original trading_env.py."""

    def __init__(self, steps: int, trading_cost_bps: float, time_cost_bps: float):
        self.trading_cost_bps = trading_cost_bps
        self.time_cost_bps = time_cost_bps
        self.steps = steps
        self.reset()

    def reset(self):
        self.step = 0
        self.actions         = np.zeros(self.steps)
        self.navs            = np.ones(self.steps)
        self.market_navs     = np.ones(self.steps)
        self.strategy_returns = np.zeros(self.steps)
        self.positions       = np.zeros(self.steps)
        self.costs           = np.zeros(self.steps)
        self.trades          = np.zeros(self.steps)
        self.market_returns  = np.zeros(self.steps)

    def take_step(self, action: int, market_return: float):
        start_position   = self.positions[max(0, self.step - 1)]
        start_nav        = self.navs[max(0, self.step - 1)]
        start_market_nav = self.market_navs[max(0, self.step - 1)]

        self.market_returns[self.step] = market_return
        self.actions[self.step] = action

        end_position = action - 1  # 0->short, 1->flat, 2->long
        n_trades     = end_position - start_position
        self.positions[self.step] = end_position
        self.trades[self.step]    = n_trades

        trade_cost = abs(n_trades) * self.trading_cost_bps
        time_cost  = 0 if n_trades else self.time_cost_bps
        self.costs[self.step] = trade_cost + time_cost

        reward = start_position * market_return - self.costs[self.step]
        self.strategy_returns[self.step] = reward

        if self.step != 0:
            self.navs[self.step]        = start_nav * (1 + self.strategy_returns[self.step])
            self.market_navs[self.step] = start_market_nav * (1 + self.market_returns[self.step])

        self.step += 1
        return reward, {"nav": self.navs[self.step - 1], "costs": self.costs[self.step - 1]}

    def result(self) -> pd.DataFrame:
        return pd.DataFrame({
            "action":          self.actions,
            "nav":             self.navs,
            "market_nav":      self.market_navs,
            "market_return":   self.market_returns,
            "strategy_return": self.strategy_returns,
            "position":        self.positions,
            "cost":            self.costs,
            "trade":           self.trades,
        })


class TradingEnvironment(gym.Env):
    """
    OpenAI Gymnasium trading environment.
    Actions: 0=SHORT, 1=HOLD, 2=LONG
    Episode: trading_days steps with random start offset.
    """
    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        df: pd.DataFrame,
        trading_days: int = 252,
        trading_cost_bps: float = 1e-3,
        time_cost_bps: float = 1e-4,
        feature_mode: str = "precomputed",
    ):
        super().__init__()
        self.trading_days     = trading_days
        self.trading_cost_bps = trading_cost_bps
        self.time_cost_bps    = time_cost_bps

        self.data_source = DataSource(df, trading_days=trading_days,
                                       feature_mode=feature_mode)
        self.simulator   = TradingSimulator(
            steps=trading_days,
            trading_cost_bps=trading_cost_bps,
            time_cost_bps=time_cost_bps,
        )

        n_features = len(self.data_source._active_cols)
        self.action_space      = spaces.Discrete(3)
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(n_features,), dtype=np.float32
        )
        self.reset()

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.data_source.reset()
        self.simulator.reset()
        obs, _, _ = self.data_source.take_step()
        return obs.astype(np.float32), {}

    def step(self, action: int):
        assert self.action_space.contains(action)
        obs, market_return, done = self.data_source.take_step()
        reward, info = self.simulator.take_step(
            action=action, market_return=market_return
        )
        return obs.astype(np.float32), float(reward), done, False, info

    def render(self):
        pass
