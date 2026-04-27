"""
Pure backtesting engine — no DB, S3, or network deps.
Importable standalone for unit tests.
"""
import math
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
        if initial_capital <= 0:
            raise ValueError(
                f"initial_capital must be > 0; got {initial_capital!r}"
            )
        if trading_cost_bps < 0:
            raise ValueError(
                f"trading_cost_bps must be >= 0; got {trading_cost_bps!r}"
            )
        if time_cost_bps < 0:
            raise ValueError(
                f"time_cost_bps must be >= 0; got {time_cost_bps!r}"
            )
        self.initial_capital = initial_capital
        self.trading_cost_bps = trading_cost_bps / 10_000
        self.time_cost_bps = time_cost_bps / 10_000
        self._seed = seed
        self.rng = np.random.default_rng(seed)

    def make_random_policy(self) -> Callable:
        """
        Return a policy that draws from this engine's RNG.

        The closure references self (not self.rng directly), so it picks up
        the RNG after run() resets it. This means a single engine called
        with the same df and same seed yields identical results across
        run() invocations, regardless of symbol ordering.
        """
        engine = self
        def _policy(_state: list) -> int:
            return int(engine.rng.integers(0, 3))
        return _policy

    def run(self, df: pd.DataFrame, policy_fn: Callable) -> dict:
        """
        df: DataFrame sorted by time with columns:
            [time, ret_1d, ret_2d, ret_5d, ret_10d, ret_21d,
             rsi, macd, atr, stoch, ultosc]
        policy_fn: callable(state_vector: list[float]) -> int
            (0=SHORT, 1=HOLD, 2=LONG). Must return 0, 1, or 2.
        Returns: metrics dict + equityCurve list.

        Caller contract — feature columns must be backward-looking:
          All ret_Nd columns and all indicators (rsi, macd, atr, stoch,
          ultosc) at row t must be computable from prices/data up to and
          including bar t (close-of-bar-t or earlier). The engine cannot
          enforce this — if the caller computes ret_5d as
          `close.pct_change(-5)` or otherwise leaks future information,
          the engine will silently produce inflated alpha. The look-ahead
          fix below shifts ret_1d for the *realized return* the policy
          earns; it does NOT scrub the feature vector.

        Semantics:
          - No look-ahead on the realized return: the action decided at
            bar t earns ret_1d at bar t+1. A DataFrame with N rows produces
            N-1 return-generating bars; the terminal row is the final close
            and contributes no P&L, no cost, and no trade count.
          - Trade units: |new_position - old_position|. A short→long flip
            counts as 2 units (two executions), so trade cost is charged
            twice. Both totalPositionChanges (bars with any change) and
            totalTradeUnits (sum of execution units) are reported.
          - time_cost_bps is charged on bars with no position change (carry
            on holding/flat).
          - If the engine was constructed with a seed, self.rng is reset at
            the start of every run() call so per-symbol results are
            reproducible regardless of the order in which symbols are run.
        """
        # Per-run RNG reset so ordering of run() calls doesn't shift results.
        if self._seed is not None:
            self.rng = np.random.default_rng(self._seed)

        # Drop the warmup window: any row missing a feature value (e.g. ret_21d
        # in the first 21 bars of a fresh symbol) is excluded entirely. This
        # replaces the prior silent NaN→0.0 substitution, which fed a "neutral"
        # signal into policies that read 0 as a valid extreme value.
        df = df.dropna(subset=FEATURE_COLS).copy()

        # Need at least two rows to form one return period.
        if len(df) < 2:
            return {}

        df = df.sort_values("time").reset_index(drop=True)
        # Time column must be strictly increasing and unique. Duplicates or
        # out-of-order rows indicate a data bug upstream (the DB query orders
        # by symbol, time) and would produce nonsensical return periods.
        if not df["time"].is_unique:
            raise ValueError("df['time'] contains duplicate timestamps")
        if not df["time"].is_monotonic_increasing:
            raise ValueError("df['time'] is not strictly increasing after sort")

        # Realized return for the decision made at bar t is next bar's ret_1d.
        realized_next = df["ret_1d"].shift(-1).to_numpy()

        nav = self.initial_capital
        market_nav = self.initial_capital
        position = 0           # -1=short, 0=flat, 1=long
        equity_curve: list[dict] = []
        position_changes = 0
        trade_units_total = 0
        # Unrounded buffers for metric computation. Reading metrics off the
        # rounded equity curve compounds rounding error across N bars
        # (~1e-4 on totalReturn at 252 bars w/ strategy_ret rounded to 1e-6),
        # which is enough to flip the sign of small alpha or move a borderline
        # Sharpe across a promotion threshold.
        navs_raw: list[float] = []
        market_navs_raw: list[float] = []
        rets_raw: list[float] = []

        # Iterate N-1 bars. The final row is the close of the last return
        # period; no new action is taken against it.
        n_decision_bars = len(df) - 1
        for i in range(n_decision_bars):
            row = df.iloc[i]
            # NaN-bearing rows were dropped above; features here are clean.
            state = [float(row[c]) for c in FEATURE_COLS]
            action = policy_fn(state)
            if action not in (0, 1, 2):
                raise ValueError(
                    f"policy_fn returned {action!r}; expected 0, 1, or 2"
                )
            new_position = action - 1  # 0→-1, 1→0, 2→1

            # NaN-feature rows (which include NaN ret_1d) were dropped above,
            # and we only iterate i < N-1, so realized_next[i] is never NaN.
            market_ret = float(realized_next[i])

            n_trade_units = abs(new_position - position)
            trade_cost = n_trade_units * self.trading_cost_bps
            time_cost = 0.0 if n_trade_units else self.time_cost_bps
            total_cost = trade_cost + time_cost

            strategy_ret = new_position * market_ret - total_cost
            nav = nav * (1 + strategy_ret)
            market_nav = market_nav * (1 + market_ret)

            if n_trade_units > 0:
                position_changes += 1
                trade_units_total += n_trade_units

            navs_raw.append(nav)
            market_navs_raw.append(market_nav)
            rets_raw.append(strategy_ret)

            # Wire format: tz-aware ISO 8601. A naive isoformat (no tz) is
            # parsed as local time by JS engines, which would shift the
            # equity curve by the viewer's UTC offset. Assume UTC for naive
            # timestamps (the trading-data convention upstream).
            ts = pd.Timestamp(row["time"])
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            equity_curve.append({
                "time":         ts.isoformat(),
                "nav":          round(nav, 4),
                "market_nav":   round(market_nav, 4),
                "position":     new_position,
                "strategy_ret": round(strategy_ret, 6),
                "market_ret":   round(market_ret, 6),
                "cost":         round(total_cost, 6),
            })

            position = new_position

        metrics = self._compute_metrics(
            navs=navs_raw,
            market_navs=market_navs_raw,
            rets=rets_raw,
            position_changes=position_changes,
            trade_units_total=trade_units_total,
        )
        if metrics:
            metrics["equityCurve"] = equity_curve
        return metrics

    def _compute_metrics(
        self,
        navs: list[float],
        market_navs: list[float],
        rets: list[float],
        position_changes: int,
        trade_units_total: int,
    ) -> dict:
        if not rets:
            return {}

        ret_arr    = np.asarray(rets, dtype=float)
        nav_arr    = np.asarray(navs, dtype=float)
        mnav_arr   = np.asarray(market_navs, dtype=float)

        final_nav     = float(nav_arr[-1])
        total_return  = (final_nav - self.initial_capital) / self.initial_capital
        market_return = (float(mnav_arr[-1]) - self.initial_capital) / self.initial_capital
        trading_days  = ret_arr.size
        ann_factor    = 252 / trading_days

        # Annualization is undefined / unrepresentable in two cases:
        #   1. NAV ≤ 0 (short blowup, corrupt ret_1d): total_return ≤ -1 →
        #      (1 + total_return) ** frac is NaN / complex.
        #   2. Huge positive total_return on a short backtest: e.g. N=1
        #      with total_return > ~15 raises OverflowError, or saturates
        #      to inf, which json.dumps(allow_nan=False) then rejects.
        # In both cases emit None rather than letting NaN/inf/exception
        # escape into the metrics blob and fail the entire report.
        def _annualize(r: float, ann: float) -> Optional[float]:
            if 1 + r <= 0:
                return None
            try:
                v = (1 + r) ** ann - 1
            except OverflowError:
                return None
            return v if math.isfinite(v) else None

        ann_return: Optional[float] = _annualize(total_return, ann_factor)
        ann_market_return: Optional[float] = _annualize(market_return, ann_factor)
        # Alpha is only defined when both legs are defined.
        alpha: Optional[float] = (
            ann_return - ann_market_return
            if ann_return is not None and ann_market_return is not None
            else None
        )
        mean_ret   = float(np.mean(ret_arr))

        # Sample std (ddof=1) matches pyfolio/quantstats/vectorbt convention.
        # Need at least 2 samples; below that, Sharpe is undefined.
        if ret_arr.size > 1:
            std_ret = float(np.std(ret_arr, ddof=1))
            sharpe: Optional[float] = float(
                mean_ret / (std_ret + 1e-12) * np.sqrt(252)
            )
        else:
            sharpe = None

        # Standard Sortino: downside deviation = sqrt(mean(min(r, 0)^2))
        # over ALL bars (target=0), not std() of just-the-negatives. Matches
        # the textbook/pyfolio definition; the prior formula structurally
        # disagreed with every third-party tool.
        downside = np.minimum(ret_arr, 0.0)
        dd_dev   = float(np.sqrt(np.mean(downside ** 2)))
        if dd_dev > 0:
            sortino: Optional[float] = float(mean_ret / dd_dev * np.sqrt(252))
        else:
            # Undefined: surfaced as None (RFC 7159 — see C1).
            sortino = None if mean_ret > 0 else 0.0

        peak   = self.initial_capital
        max_dd = 0.0
        for n in nav_arr:
            if n > peak:
                peak = n
            dd = (peak - n) / peak
            if dd > max_dd:
                max_dd = dd

        wins          = int(np.sum(ret_arr > 0))
        # ret_arr.size > 0 is guaranteed by the `if not curve` guard above
        # plus run()'s `len(df) < 2` short-circuit.
        win_rate      = wins / ret_arr.size
        gross_profit  = float(np.sum(ret_arr[ret_arr > 0]))
        gross_loss    = float(-np.sum(ret_arr[ret_arr < 0]))
        profit_factor: Optional[float] = (
            gross_profit / gross_loss if gross_loss > 0 else None
        )

        return {
            "finalNav":               round(final_nav, 2),
            "initialCapital":         self.initial_capital,
            "totalReturn":            round(total_return, 4),
            "annualizedReturn":       None if ann_return is None else round(ann_return, 4),
            "marketReturn":           round(market_return, 4),
            "annualizedMarketReturn": None if ann_market_return is None else round(ann_market_return, 4),
            "alpha":                  None if alpha is None else round(alpha, 4),
            "sharpeRatio":            None if sharpe is None else round(sharpe, 3),
            "sortinoRatio":           None if sortino is None else round(sortino, 3),
            "maxDrawdown":            round(max_dd, 4),
            "winRate":                round(win_rate, 4),
            "profitFactor":           None if profit_factor is None else round(profit_factor, 3),
            "totalPositionChanges":   position_changes,
            "totalTradeUnits":        trade_units_total,
            "tradingDays":            trading_days,
        }


def buy_and_hold_policy(_state: list) -> int:
    return 2  # Always LONG
