"""
Trading environment for RL training.
Adapted from 22_deep_reinforcement_learning/trading_env.py
Changes: loads from PostgreSQL/parquet instead of assets.h5

Supports single-stock and multi-stock training:
  - Single stock: DataFrame indexed by date (no 'symbol' column)
  - Multi stock: DataFrame with 'symbol' column; each episode randomly
    selects a stock and time offset within it.
"""
import logging
import sys
import os
import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))
from feature_columns import (
    TECHNICAL_COLS, SHARADAR_COLS, ALL_FEATURE_COLS,
    VALID_FEATURE_MODES, detect_active_cols,
)

log = logging.getLogger(__name__)


class DataSource:
    """
    Loads & preprocesses daily bar data.

    Supports:
      - Single stock (DataFrame indexed by date, no 'symbol' column)
      - Multi stock (DataFrame with 'symbol' column — each reset() picks a
        random stock, then a random time offset within it)

    Feature modes:
      - "auto" (default): like precomputed but drops SHARADAR cols that are
        entirely NaN across all stocks (e.g. ETFs).
      - "precomputed": expects 20 pre-computed feature columns.
      - "compute": recomputes 10 technical indicators from OHLCV.
    """

    FEATURE_COLS = ALL_FEATURE_COLS  # 20 features

    def __init__(self, df: pd.DataFrame, trading_days: int = 252,
                 normalize: bool = True, feature_mode: str = "precomputed",
                 train_ratio: float = 1.0):
        """
        df: DataFrame indexed by date (single stock) or with 'symbol' column (multi stock).
        feature_mode: "precomputed", "compute", or "auto"
        train_ratio: fraction of data to use for training (0 < r <= 1).
                     If < 1, the remainder is held out for validation.
                     Split is temporal — train on earlier data, test on later.
        """
        if feature_mode not in VALID_FEATURE_MODES:
            raise ValueError(
                f"Invalid feature_mode '{feature_mode}'. "
                f"Must be one of {VALID_FEATURE_MODES}"
            )
        self.trading_days = trading_days
        self.normalize = normalize
        self.feature_mode = feature_mode
        self.train_ratio = train_ratio

        # Detect multi-stock vs single-stock
        self._multi_stock = "symbol" in df.columns
        if self._multi_stock:
            self._symbols = sorted(df["symbol"].unique().tolist())
            log.info("Multi-stock mode: %d symbols — %s", len(self._symbols), self._symbols)
        else:
            self._symbols = [None]  # sentinel for single-stock

        # Determine active feature columns (before per-stock preprocessing)
        if feature_mode == "compute":
            self._active_cols = list(TECHNICAL_COLS)
        elif feature_mode == "auto":
            self._active_cols = detect_active_cols(df)
            dropped = set(ALL_FEATURE_COLS) - set(self._active_cols)
            if dropped:
                log.info(
                    "Auto feature mode: dropped %d all-NaN columns: %s",
                    len(dropped), sorted(dropped),
                )
        else:
            self._active_cols = list(ALL_FEATURE_COLS)

        # Preprocess and split into per-stock data
        self._stock_data = {}   # {symbol: DataFrame of scaled features}
        self._stock_ret1d = {}  # {symbol: Series of raw ret_1d}
        self._stock_train_end = {}  # {symbol: last train index}

        if self._multi_stock:
            for sym in self._symbols:
                sym_df = df[df["symbol"] == sym].copy()
                if "symbol" in sym_df.columns:
                    sym_df = sym_df.drop(columns=["symbol"])
                # Index by date for consistent handling
                if "time" in sym_df.columns:
                    sym_df["time"] = pd.to_datetime(sym_df["time"])
                    sym_df = sym_df.set_index("time")
                self._preprocess_stock(sym, sym_df)
        else:
            self._preprocess_stock(None, df)

        # Remove stocks with insufficient data
        min_rows = trading_days + 1
        short_stocks = [s for s, d in self._stock_data.items() if len(d) < min_rows]
        for s in short_stocks:
            log.warning(
                "Dropping %s: only %d rows (need %d for %d trading_days)",
                s, len(self._stock_data[s]), min_rows, trading_days,
            )
            del self._stock_data[s]
            del self._stock_ret1d[s]
            if s in self._stock_train_end:
                del self._stock_train_end[s]
            if s in self._symbols:
                self._symbols.remove(s)

        if not self._stock_data:
            raise ValueError("No stocks have enough data for the requested trading_days")

        # Aggregate stats (for backward compat — uses first/only stock)
        first_key = self._symbols[0]
        self.data = self._stock_data[first_key]
        self._ret_1d = self._stock_ret1d[first_key]
        self.min_values = self.data.min()
        self.max_values = self.data.max()

        self.step = 0
        self.offset = None
        self._current_symbol = first_key

    def _preprocess_stock(self, symbol, df: pd.DataFrame):
        """Preprocess a single stock's data and store in _stock_data/_stock_ret1d."""
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
            # Precomputed / auto mode: replace inf before fillna
            df = df.replace([np.inf, -np.inf], np.nan)
            # Only fill SHARADAR cols that are in _active_cols
            sharadar_active = [c for c in SHARADAR_COLS if c in self._active_cols and c in df.columns]
            if sharadar_active:
                df[sharadar_active] = df[sharadar_active].fillna(0)
            # Fill any missing feature columns with 0
            for c in self._active_cols:
                if c not in df.columns:
                    log.warning("Missing feature column '%s' for %s, filling with 0", c, symbol)
                    df[c] = 0.0

        df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=TECHNICAL_COLS)

        if df.empty:
            log.warning("No valid rows for %s after preprocessing", symbol)
            return

        # Store raw ret_1d separately for reward signal
        ret_1d = df["ret_1d"].copy()

        # Train/test split (temporal)
        n = len(df)
        train_end = int(n * self.train_ratio)
        if train_end < 1:
            train_end = 1
        self._stock_train_end[symbol] = train_end

        # Scale features per-stock (different price regimes)
        if self.normalize:
            # Scale using training data stats only to prevent lookahead
            train_slice = df[self._active_cols].iloc[:train_end]
            train_mean = train_slice.mean()
            train_std = train_slice.std().replace(0, 1)  # avoid div by zero
            df[self._active_cols] = (df[self._active_cols] - train_mean) / train_std

        self._stock_data[symbol] = df[self._active_cols]
        self._stock_ret1d[symbol] = ret_1d

    def reset(self, test_mode: bool = False):
        """Reset for a new episode.

        test_mode=False: sample from training portion only.
        test_mode=True: sample from test (held-out) portion only.
        """
        # Pick a random stock
        self._current_symbol = self._symbols[np.random.randint(len(self._symbols))]
        data = self._stock_data[self._current_symbol]
        train_end = self._stock_train_end[self._current_symbol]

        if test_mode and self.train_ratio < 1.0:
            # Sample from test portion
            low = train_end
            high = len(data) - self.trading_days
        else:
            # Sample from training portion
            low = 0
            high = train_end - self.trading_days

        high = max(high, low + 1)
        self.offset = np.random.randint(low=low, high=high)
        self.step = 0

        # Update convenience references
        self.data = data
        self._ret_1d = self._stock_ret1d[self._current_symbol]

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

    Supports single-stock and multi-stock DataFrames.
    If df has a 'symbol' column, each episode randomly selects a stock.
    """
    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        df: pd.DataFrame,
        trading_days: int = 252,
        trading_cost_bps: float = 1e-3,
        time_cost_bps: float = 1e-4,
        feature_mode: str = "auto",
        train_ratio: float = 1.0,
    ):
        super().__init__()
        self.trading_days     = trading_days
        self.trading_cost_bps = trading_cost_bps
        self.time_cost_bps    = time_cost_bps
        self._test_mode       = False

        self.data_source = DataSource(
            df, trading_days=trading_days,
            feature_mode=feature_mode,
            train_ratio=train_ratio,
        )
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

    def set_test_mode(self, enabled: bool = True):
        """Switch between train and test (held-out) data for episodes."""
        self._test_mode = enabled

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.data_source.reset(test_mode=self._test_mode)
        self.simulator.reset()
        obs, _, _ = self.data_source.take_step()
        return obs.astype(np.float32), {}

    def step(self, action: int):
        assert self.action_space.contains(action)
        obs, market_return, done = self.data_source.take_step()
        reward, info = self.simulator.take_step(
            action=action, market_return=market_return
        )
        # Include current symbol in info for logging
        info["symbol"] = self.data_source._current_symbol
        return obs.astype(np.float32), float(reward), done, False, info

    def render(self):
        pass
