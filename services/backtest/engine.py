"""
Pure backtesting engine — no DB, S3, or network deps.
Importable standalone for unit tests.
"""
from typing import Callable, Optional

import pandas as pd
import numpy as np


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
        if seed is not None:
            np.random.seed(seed)

    def run(self, df: pd.DataFrame, policy_fn: Callable) -> dict:
        """
        df: DataFrame sorted by time with columns:
            [time, close, ret_1d, ret_2d, ret_5d, ret_10d, ret_21d,
             rsi, macd, atr, stoch, ultosc]
        policy_fn: callable(state_vector: list[float]) -> int (0=SHORT, 1=HOLD, 2=LONG)
        Returns: metrics dict + equity_curve list
        """
        df = df.sort_values("time").reset_index(drop=True)
        feature_cols = [
            "ret_1d", "ret_2d", "ret_5d", "ret_10d", "ret_21d",
            "rsi", "macd", "atr", "stoch", "ultosc",
        ]

        nav = self.initial_capital
        market_nav = self.initial_capital
        position = 0           # -1=short, 0=flat, 1=long
        equity_curve: list[dict] = []
        trades = 0

        for _, row in df.iterrows():
            state = [float(row[c]) for c in feature_cols]
            action = policy_fn(state)
            new_position = action - 1  # 0→-1, 1→0, 2→1

            market_ret = float(row["ret_1d"]) if not pd.isna(row["ret_1d"]) else 0.0

            n_trades = abs(new_position - position)
            trade_cost = n_trades * self.trading_cost_bps
            time_cost  = 0.0 if n_trades else self.time_cost_bps
            total_cost = trade_cost + time_cost

            strategy_ret = position * market_ret - total_cost
            nav          = nav * (1 + strategy_ret)
            market_nav   = market_nav * (1 + market_ret)

            if n_trades > 0:
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
        ret_arr    = np.array(rets)
        sharpe     = float(np.mean(ret_arr) / (np.std(ret_arr) + 1e-9) * np.sqrt(252))

        neg_rets = ret_arr[ret_arr < 0]
        sortino  = float(np.mean(ret_arr) / (np.std(neg_rets) + 1e-9) * np.sqrt(252))

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
            "finalNav":          round(final_nav, 2),
            "initialCapital":    self.initial_capital,
            "totalReturn":       round(total_return, 4),
            "annualizedReturn":  round(ann_return, 4),
            "marketReturn":      round(market_return, 4),
            "alpha":             round(ann_return - market_return * ann_factor, 4),
            "sharpeRatio":       round(sharpe, 3),
            "sortinoRatio":      round(sortino, 3),
            "maxDrawdown":       round(max_dd, 4),
            "winRate":           round(win_rate, 4),
            "profitFactor":      round(profit_factor, 3),
            "totalTrades":       n_trades,
            "tradingDays":       trading_days,
            "equityCurve":       curve,
        }


def buy_and_hold_policy(_state: list) -> int:
    return 2  # Always LONG


def random_policy(_state: list) -> int:
    return int(np.random.randint(0, 3))
