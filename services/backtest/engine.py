"""
Pure backtesting engine — no DB, S3, or network deps.
Importable standalone for unit tests.
"""
from typing import Callable, Optional

import pandas as pd
import numpy as np


FEATURE_COLS = [
    "ret_1d", "ret_2d", "ret_5d", "ret_10d", "ret_21d",
    "rsi", "macd", "atr", "stoch", "ultosc",
]


class BacktestEngine:
    def __init__(
        self,
        initial_capital: float = 100_000,
        trading_cost_bps: float = 10,
        time_cost_bps: float = 1,
        seed: Optional[int] = None,
    ):
        self.initial_capital = initial_capital
        self.trading_cost_bps = trading_cost_bps / 10_000
        self.time_cost_bps = time_cost_bps / 10_000
        self.rng = np.random.default_rng(seed)

    def make_random_policy(self) -> Callable:
        """Return a policy that draws from this engine's isolated RNG."""
        rng = self.rng
        def _policy(_state: list) -> int:
            return int(rng.integers(0, 3))
        return _policy

    def run(self, df: pd.DataFrame, policy_fn: Callable) -> dict:
        """
        df: DataFrame sorted by time with columns:
            [time, ret_1d, ret_2d, ret_5d, ret_10d, ret_21d,
             rsi, macd, atr, stoch, ultosc]
        policy_fn: callable(state_vector: list[float]) -> int
            (0=SHORT, 1=HOLD, 2=LONG). Must return 0, 1, or 2.
        Returns: metrics dict + equity_curve list.

        Semantics:
          - No look-ahead: the action decided at bar t earns the realized return
            at bar t+1 (ret_1d shifted by -1). The final bar contributes no P&L.
          - Trade units: |new_position - old_position|. A short→long flip counts
            as 2 units (two executions), so trade cost is charged twice.
          - time_cost_bps is charged on bars with no position change (carry on
            holding/flat).
        """
        if df.empty:
            return {}

        df = df.sort_values("time").reset_index(drop=True)
        # Realized return for the decision made at bar t is next bar's ret_1d.
        realized_next = df["ret_1d"].shift(-1).to_numpy()

        nav = self.initial_capital
        market_nav = self.initial_capital
        position = 0           # -1=short, 0=flat, 1=long
        equity_curve: list[dict] = []
        trades = 0

        n_rows = len(df)
        for i, row in df.iterrows():
            state = [
                0.0 if pd.isna(row[c]) else float(row[c])
                for c in FEATURE_COLS
            ]
            action = policy_fn(state)
            if action not in (0, 1, 2):
                raise ValueError(
                    f"policy_fn returned {action!r}; expected 0, 1, or 2"
                )
            new_position = action - 1  # 0→-1, 1→0, 2→1

            # P&L: no look-ahead. Final row has no next-bar return → 0.
            if i < n_rows - 1:
                raw_next = realized_next[i]
                market_ret = 0.0 if pd.isna(raw_next) else float(raw_next)
            else:
                market_ret = 0.0

            n_trade_units = abs(new_position - position)
            trade_cost = n_trade_units * self.trading_cost_bps
            time_cost = 0.0 if n_trade_units else self.time_cost_bps
            total_cost = trade_cost + time_cost

            strategy_ret = new_position * market_ret - total_cost
            nav = nav * (1 + strategy_ret)
            market_nav = market_nav * (1 + market_ret)

            if n_trade_units > 0:
                trades += 1

            equity_curve.append({
                "time":         str(row["time"]),
                "nav":          round(nav, 4),
                "market_nav":   round(market_nav, 4),
                "position":     new_position,
                "strategy_ret": round(strategy_ret, 6),
                "market_ret":   round(market_ret, 6),
                "cost":         round(total_cost, 6),
            })

            position = new_position

        return self._compute_metrics(equity_curve, trades)

    def _compute_metrics(self, curve: list[dict], n_trades: int) -> dict:
        if not curve:
            return {}

        navs  = [r["nav"] for r in curve]
        mnavs = [r["market_nav"] for r in curve]
        rets  = [r["strategy_ret"] for r in curve]

        final_nav     = navs[-1]
        total_return  = (final_nav - self.initial_capital) / self.initial_capital
        market_return = (mnavs[-1] - self.initial_capital) / self.initial_capital
        trading_days  = len(curve)
        ann_factor    = 252 / trading_days if trading_days > 0 else 1

        ann_return = (1 + total_return) ** ann_factor - 1
        ann_market_return = (1 + market_return) ** ann_factor - 1
        ret_arr    = np.array(rets)
        sharpe     = float(np.mean(ret_arr) / (np.std(ret_arr) + 1e-9) * np.sqrt(252))

        neg_rets = ret_arr[ret_arr < 0]
        if neg_rets.size == 0:
            sortino = float("inf")
        else:
            sortino = float(
                np.mean(ret_arr) / (np.std(neg_rets) + 1e-9) * np.sqrt(252)
            )

        peak   = self.initial_capital
        max_dd = 0.0
        for n in navs:
            if n > peak:
                peak = n
            dd = (peak - n) / peak
            if dd > max_dd:
                max_dd = dd

        wins          = sum(1 for r in rets if r > 0)
        win_rate      = wins / len(rets) if rets else 0.0
        gross_profit  = sum(r for r in rets if r > 0)
        gross_loss    = abs(sum(r for r in rets if r < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        return {
            "finalNav":               round(final_nav, 2),
            "initialCapital":         self.initial_capital,
            "totalReturn":            round(total_return, 4),
            "annualizedReturn":       round(ann_return, 4),
            "marketReturn":           round(market_return, 4),
            "annualizedMarketReturn": round(ann_market_return, 4),
            "alpha":                  round(ann_return - ann_market_return, 4),
            "sharpeRatio":            round(sharpe, 3),
            "sortinoRatio":           round(sortino, 3),
            "maxDrawdown":            round(max_dd, 4),
            "winRate":                round(win_rate, 4),
            "profitFactor":           round(profit_factor, 3),
            "totalTrades":            n_trades,
            "tradingDays":            trading_days,
            "equityCurve":            curve,
        }


def buy_and_hold_policy(_state: list) -> int:
    return 2  # Always LONG
