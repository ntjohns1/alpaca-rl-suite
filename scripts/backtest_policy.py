#!/usr/bin/env python3
"""
⚠️  DEPRECATED — Use the unified CLI or Backtest service instead.

    CLI:  alpaca-rl backtest run --policy-id <id> --symbol SPY
    API:  POST http://localhost:8001/backtest/run

The backtest service now handles policy loading from S3, chart generation,
and metric calculation. This script is kept for reference only.
─────────────────────────────────────────────────────────────────────────

Backtest trained RL policy on held-out test data.

Usage:
    python scripts/backtest_policy.py \
      --policy-path models/policy_20260303.zip \
      --symbol SPY \
      --initial-capital 100000 \
      --output-dir results/

This script:
1. Loads a trained Stable-Baselines3 DQN model
2. Fetches 2024 test data from PostgreSQL
3. Runs backtest with proper feature engineering
4. Calculates performance metrics (Sharpe, drawdown, win rate)
5. Generates visualizations (equity curve, drawdown, positions)
6. Evaluates promotion criteria
"""
import argparse
import os
import sys
import json
import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from sklearn.preprocessing import scale
import ta


def load_data_from_db(symbol: str, start_date: str, end_date: str, database_url: str) -> pd.DataFrame:
    """Load bar data from PostgreSQL for the test period"""
    print(f"📊 Loading data for {symbol} ({start_date} to {end_date})...")
    
    conn = psycopg2.connect(database_url)
    
    query = """
        SELECT 
            time::date as date,
            open::float,
            high::float,
            low::float,
            close::float,
            volume::bigint
        FROM bar_1d 
        WHERE symbol = %s 
          AND time >= %s::date 
          AND time <= %s::date
        ORDER BY time
    """
    
    df = pd.read_sql(query, conn, params=(symbol, start_date, end_date))
    conn.close()
    
    if len(df) == 0:
        raise ValueError(f"No data found for {symbol} in period {start_date} to {end_date}")
    
    print(f"  ✓ Loaded {len(df)} bars")
    print(f"  Date range: {df['date'].min()} to {df['date'].max()}")
    
    return df


def calculate_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate technical features matching trading_env.py.
    
    Features: returns, ret_2, ret_5, ret_10, ret_21, rsi, macd, atr, stoch, ultosc
    """
    print("🔧 Calculating features...")
    
    df = df.copy()
    df = df.set_index('date')
    df.index = pd.to_datetime(df.index)
    
    # Returns
    df["returns"] = df["close"].pct_change()
    df["ret_2"] = df["close"].pct_change(2)
    df["ret_5"] = df["close"].pct_change(5)
    df["ret_10"] = df["close"].pct_change(10)
    df["ret_21"] = df["close"].pct_change(21)
    
    # Technical indicators
    df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
    
    macd_obj = ta.trend.MACD(df["close"])
    df["macd"] = macd_obj.macd_signal()
    
    df["atr"] = ta.volatility.AverageTrueRange(
        df["high"], df["low"], df["close"], window=14
    ).average_true_range()
    
    stoch_obj = ta.momentum.StochasticOscillator(
        df["high"], df["low"], df["close"], window=14
    )
    df["stoch"] = stoch_obj.stoch_signal() - stoch_obj.stoch()
    
    df["ultosc"] = ta.momentum.UltimateOscillator(
        df["high"], df["low"], df["close"]
    ).ultimate_oscillator()
    
    # Remove inf/nan
    df = df.replace([np.inf, -np.inf], np.nan)
    
    feature_cols = [
        "returns", "ret_2", "ret_5", "ret_10", "ret_21",
        "rsi", "macd", "atr", "stoch", "ultosc"
    ]
    
    # Drop rows with NaN in features
    df_clean = df.dropna(subset=feature_cols)
    
    print(f"  ✓ Calculated features ({len(df_clean)} valid rows after dropping NaN)")
    
    return df_clean


def normalize_features(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize features using sklearn scale (matching training)"""
    df = df.copy()
    
    feature_cols = [
        "returns", "ret_2", "ret_5", "ret_10", "ret_21",
        "rsi", "macd", "atr", "stoch", "ultosc"
    ]
    
    # Save returns before normalization (needed for backtest)
    returns_orig = df["returns"].copy()
    
    # Normalize all features
    df[feature_cols] = scale(df[feature_cols])
    
    # Restore original returns (don't scale returns for reward calculation)
    df["returns"] = returns_orig
    
    return df


def load_policy(policy_path: str):
    """Load Stable-Baselines3 DQN model and return policy function"""
    print(f"🤖 Loading policy from {policy_path}...")
    
    from stable_baselines3 import DQN
    
    if not os.path.exists(policy_path):
        raise FileNotFoundError(f"Policy file not found: {policy_path}")
    
    model = DQN.load(policy_path, device="cpu")
    
    def policy_fn(state: list) -> int:
        """Policy function: state -> action (0=SHORT, 1=HOLD, 2=LONG)"""
        obs = np.array(state, dtype=np.float32).reshape(1, -1)
        action, _ = model.predict(obs, deterministic=True)
        return int(action.item())
    
    print("  ✓ Policy loaded")
    return policy_fn


def run_backtest(df: pd.DataFrame, policy_fn, initial_capital: float, 
                 trading_cost_bps: float, time_cost_bps: float) -> dict:
    """
    Run backtest on test data.
    
    Returns dict with metrics and equity curve.
    """
    print(f"📈 Running backtest...")
    print(f"  Initial capital: ${initial_capital:,.0f}")
    print(f"  Trading cost: {trading_cost_bps} bps")
    print(f"  Time cost: {time_cost_bps} bps")
    
    df = df.sort_index().reset_index()
    
    feature_cols = [
        "ret_2", "ret_5", "ret_10", "ret_21",  # Note: ret_2 not returns for state
        "rsi", "macd", "atr", "stoch", "ultosc"
    ]
    
    # Add returns as first feature (matching training env)
    feature_cols = ["returns"] + feature_cols
    
    nav = initial_capital
    market_nav = initial_capital
    position = 0  # -1=short, 0=flat, 1=long
    equity_curve = []
    trades = 0
    
    trading_cost = trading_cost_bps / 10_000
    time_cost = time_cost_bps / 10_000
    
    for idx, row in df.iterrows():
        # Get state (normalized features)
        state = [float(row[c]) for c in feature_cols]
        
        # Get action from policy
        action = policy_fn(state)
        new_position = action - 1  # 0->-1, 1->0, 2->1
        
        # Market return (use original returns, not normalized)
        market_ret = float(row["returns"]) if not pd.isna(row["returns"]) else 0.0
        
        # Calculate costs
        n_trades = abs(new_position - position)
        trade_cost_val = n_trades * trading_cost
        time_cost_val = 0.0 if n_trades else time_cost
        total_cost = trade_cost_val + time_cost_val
        
        # Calculate strategy return
        strategy_ret = position * market_ret - total_cost
        
        # Update NAVs
        nav = nav * (1 + strategy_ret)
        market_nav = market_nav * (1 + market_ret)
        
        if n_trades > 0:
            trades += 1
        
        equity_curve.append({
            "date": str(row["date"]),
            "nav": round(nav, 2),
            "market_nav": round(market_nav, 2),
            "position": new_position,
            "strategy_ret": round(strategy_ret, 6),
            "market_ret": round(market_ret, 6),
            "cost": round(total_cost, 6),
        })
        
        position = new_position
    
    # Calculate metrics
    metrics = calculate_metrics(equity_curve, initial_capital, trades)
    
    print(f"  ✓ Backtest complete ({len(equity_curve)} days, {trades} trades)")
    
    return {
        "metrics": metrics,
        "equity_curve": equity_curve
    }


def calculate_metrics(equity_curve: list, initial_capital: float, n_trades: int) -> dict:
    """Calculate performance metrics from equity curve"""
    
    navs = [r["nav"] for r in equity_curve]
    market_navs = [r["market_nav"] for r in equity_curve]
    rets = [r["strategy_ret"] for r in equity_curve]
    
    final_nav = navs[-1]
    total_return = (final_nav - initial_capital) / initial_capital
    market_return = (market_navs[-1] - initial_capital) / initial_capital
    
    trading_days = len(equity_curve)
    ann_factor = 252 / trading_days if trading_days > 0 else 1
    
    ann_return = (1 + total_return) ** ann_factor - 1
    
    # Sharpe ratio
    ret_arr = np.array(rets)
    sharpe = float(np.mean(ret_arr) / (np.std(ret_arr) + 1e-9) * np.sqrt(252))
    
    # Sortino ratio
    neg_rets = ret_arr[ret_arr < 0]
    sortino = float(np.mean(ret_arr) / (np.std(neg_rets) + 1e-9) * np.sqrt(252))
    
    # Max drawdown
    peak = initial_capital
    max_dd = 0.0
    for nav in navs:
        if nav > peak:
            peak = nav
        dd = (peak - nav) / peak
        if dd > max_dd:
            max_dd = dd
    
    # Win rate
    wins = sum(1 for r in rets if r > 0)
    win_rate = wins / len(rets) if rets else 0.0
    
    # Profit factor
    gross_profit = sum(r for r in rets if r > 0)
    gross_loss = abs(sum(r for r in rets if r < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    
    # Alpha
    alpha = ann_return - market_return * ann_factor
    
    return {
        "final_nav": round(final_nav, 2),
        "initial_capital": initial_capital,
        "total_return": round(total_return, 4),
        "annualized_return": round(ann_return, 4),
        "market_return": round(market_return, 4),
        "alpha": round(alpha, 4),
        "sharpe_ratio": round(sharpe, 3),
        "sortino_ratio": round(sortino, 3),
        "max_drawdown": round(max_dd, 4),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 3),
        "total_trades": n_trades,
        "trading_days": trading_days,
    }


def evaluate_promotion_criteria(metrics: dict) -> dict:
    """Evaluate if model meets promotion criteria"""
    
    criteria = {
        "sharpe_gt_1": metrics["sharpe_ratio"] > 1.0,
        "drawdown_lt_15pct": metrics["max_drawdown"] < 0.15,
        "win_rate_gt_50pct": metrics["win_rate"] > 0.50,
        "beats_market": metrics["alpha"] > 0,
    }
    
    criteria["recommend_promotion"] = all(criteria.values())
    
    return criteria


def create_visualizations(equity_curve: list, metrics: dict, symbol: str, output_dir: Path):
    """Create visualization plots"""
    print("📊 Creating visualizations...")
    
    df = pd.DataFrame(equity_curve)
    df["date"] = pd.to_datetime(df["date"])
    
    # 1. Equity Curve (Strategy vs Buy-and-Hold)
    fig, ax = plt.subplots(figsize=(12, 6))
    
    ax.plot(df["date"], df["nav"], label="RL Strategy", color="#2E86DE", linewidth=2)
    ax.plot(df["date"], df["market_nav"], label="Buy & Hold", color="#95A5A6", linewidth=2, linestyle="--")
    
    # Shade outperformance/underperformance
    ax.fill_between(df["date"], df["nav"], df["market_nav"], 
                     where=(df["nav"] >= df["market_nav"]), 
                     alpha=0.2, color="green", label="Outperformance")
    ax.fill_between(df["date"], df["nav"], df["market_nav"], 
                     where=(df["nav"] < df["market_nav"]), 
                     alpha=0.2, color="red", label="Underperformance")
    
    ax.set_xlabel("Date", fontsize=12)
    ax.set_ylabel("Portfolio Value ($)", fontsize=12)
    ax.set_title(f"{symbol} Backtest: Equity Curve (2024)", fontsize=14, fontweight="bold")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    plt.xticks(rotation=45)
    plt.tight_layout()
    
    equity_path = output_dir / f"backtest_{symbol}_equity.png"
    plt.savefig(equity_path, dpi=150)
    plt.close()
    print(f"  ✓ Saved {equity_path}")
    
    # 2. Drawdown Chart
    fig, ax = plt.subplots(figsize=(12, 5))
    
    # Calculate drawdown series
    peak = metrics["initial_capital"]
    drawdowns = []
    for nav in df["nav"]:
        if nav > peak:
            peak = nav
        dd = (peak - nav) / peak
        drawdowns.append(-dd * 100)  # Convert to percentage
    
    ax.fill_between(df["date"], 0, drawdowns, color="#E74C3C", alpha=0.6)
    ax.plot(df["date"], drawdowns, color="#C0392B", linewidth=1.5)
    
    ax.set_xlabel("Date", fontsize=12)
    ax.set_ylabel("Drawdown (%)", fontsize=12)
    ax.set_title(f"{symbol} Backtest: Drawdown from Peak", fontsize=14, fontweight="bold")
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    plt.xticks(rotation=45)
    plt.tight_layout()
    
    drawdown_path = output_dir / f"backtest_{symbol}_drawdown.png"
    plt.savefig(drawdown_path, dpi=150)
    plt.close()
    print(f"  ✓ Saved {drawdown_path}")
    
    # 3. Position Distribution
    fig, ax = plt.subplots(figsize=(8, 6))
    
    position_counts = df["position"].value_counts().sort_index()
    position_labels = {-1: "Short", 0: "Flat", 1: "Long"}
    
    colors = ["#E74C3C", "#95A5A6", "#27AE60"]
    bars = ax.bar([position_labels[p] for p in position_counts.index], 
                   position_counts.values, 
                   color=[colors[p+1] for p in position_counts.index])
    
    ax.set_ylabel("Days", fontsize=12)
    ax.set_title(f"{symbol} Backtest: Position Distribution", fontsize=14, fontweight="bold")
    ax.grid(True, alpha=0.3, axis='y')
    
    # Add value labels on bars
    for bar in bars:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height,
                f'{int(height)}',
                ha='center', va='bottom', fontsize=11)
    
    plt.tight_layout()
    
    positions_path = output_dir / f"backtest_{symbol}_positions.png"
    plt.savefig(positions_path, dpi=150)
    plt.close()
    print(f"  ✓ Saved {positions_path}")


def print_summary(metrics: dict, criteria: dict, symbol: str):
    """Print backtest summary to console"""
    
    print("\n" + "="*60)
    print("BACKTEST RESULTS".center(60))
    print("="*60)
    print(f"\nSymbol: {symbol}")
    print(f"Period: 2024-01-01 to 2024-12-31 ({metrics['trading_days']} days)")
    print(f"Initial Capital: ${metrics['initial_capital']:,.0f}")
    
    print("\n" + "-"*60)
    print("PERFORMANCE METRICS")
    print("-"*60)
    print(f"  Total Return:      {metrics['total_return']*100:>7.2f}%")
    print(f"  Annualized Return: {metrics['annualized_return']*100:>7.2f}%")
    print(f"  Market Return:     {metrics['market_return']*100:>7.2f}%")
    print(f"  Alpha:             {metrics['alpha']*100:>7.2f}%")
    
    print("\n" + "-"*60)
    print("RISK METRICS")
    print("-"*60)
    print(f"  Sharpe Ratio:      {metrics['sharpe_ratio']:>7.2f}")
    print(f"  Sortino Ratio:     {metrics['sortino_ratio']:>7.2f}")
    print(f"  Max Drawdown:      {metrics['max_drawdown']*100:>7.2f}%")
    
    print("\n" + "-"*60)
    print("TRADING METRICS")
    print("-"*60)
    print(f"  Win Rate:          {metrics['win_rate']*100:>7.2f}%")
    print(f"  Profit Factor:     {metrics['profit_factor']:>7.2f}")
    print(f"  Total Trades:      {metrics['total_trades']:>7}")
    
    print("\n" + "-"*60)
    print("PROMOTION CRITERIA")
    print("-"*60)
    
    def status(passed):
        return "✅ PASS" if passed else "❌ FAIL"
    
    print(f"  {status(criteria['sharpe_gt_1'])}: Sharpe Ratio > 1.0")
    print(f"  {status(criteria['drawdown_lt_15pct'])}: Max Drawdown < 15%")
    print(f"  {status(criteria['win_rate_gt_50pct'])}: Win Rate > 50%")
    print(f"  {status(criteria['beats_market'])}: Beats Buy-and-Hold")
    
    print("\n" + "="*60)
    if criteria["recommend_promotion"]:
        print("✅ RECOMMENDATION: PROMOTE TO PRODUCTION".center(60))
    else:
        print("❌ RECOMMENDATION: DO NOT PROMOTE".center(60))
    print("="*60 + "\n")


def save_report(metrics: dict, criteria: dict, equity_curve: list, 
                symbol: str, policy_path: str, output_dir: Path):
    """Save detailed JSON report"""
    
    report = {
        "metadata": {
            "symbol": symbol,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "policy_path": policy_path,
            "backtest_date": datetime.utcnow().isoformat(),
        },
        "metrics": metrics,
        "promotion_criteria": criteria,
        "equity_curve": equity_curve,
    }
    
    report_path = output_dir / f"backtest_{symbol}_{datetime.now().strftime('%Y%m%d')}.json"
    
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    
    print(f"💾 Saved detailed report: {report_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Backtest trained RL policy on 2024 test data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic backtest
  python scripts/backtest_policy.py \\
    --policy-path models/policy_20260303.zip \\
    --symbol SPY

  # Custom capital and output directory
  python scripts/backtest_policy.py \\
    --policy-path models/policy_20260303.zip \\
    --symbol SPY \\
    --initial-capital 50000 \\
    --output-dir results/my_backtest/
        """
    )
    
    parser.add_argument("--policy-path", required=True, 
                       help="Path to trained policy (.zip file)")
    parser.add_argument("--symbol", required=True,
                       help="Stock symbol (e.g., SPY)")
    parser.add_argument("--initial-capital", type=float, default=100000,
                       help="Initial capital (default: 100000)")
    parser.add_argument("--trading-cost-bps", type=float, default=10,
                       help="Trading cost in basis points (default: 10)")
    parser.add_argument("--time-cost-bps", type=float, default=1,
                       help="Time cost in basis points (default: 1)")
    parser.add_argument("--output-dir", default="results",
                       help="Output directory for results (default: results/)")
    parser.add_argument("--database-url",
                       help="PostgreSQL connection string (or use DATABASE_URL env var)")
    
    args = parser.parse_args()
    
    # Get database URL
    database_url = args.database_url or os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ Error: DATABASE_URL not set. Use --database-url or set DATABASE_URL environment variable.")
        return 1
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # 1. Load data
        df = load_data_from_db(args.symbol, "2024-01-01", "2024-12-31", database_url)
        
        # 2. Calculate features
        df = calculate_features(df)
        
        # 3. Normalize features
        df = normalize_features(df)
        
        # 4. Load policy
        policy_fn = load_policy(args.policy_path)
        
        # 5. Run backtest
        results = run_backtest(
            df, 
            policy_fn, 
            args.initial_capital,
            args.trading_cost_bps,
            args.time_cost_bps
        )
        
        # 6. Evaluate promotion criteria
        criteria = evaluate_promotion_criteria(results["metrics"])
        
        # 7. Create visualizations
        create_visualizations(
            results["equity_curve"],
            results["metrics"],
            args.symbol,
            output_dir
        )
        
        # 8. Print summary
        print_summary(results["metrics"], criteria, args.symbol)
        
        # 9. Save report
        save_report(
            results["metrics"],
            criteria,
            results["equity_curve"],
            args.symbol,
            args.policy_path,
            output_dir
        )
        
        print(f"\n✅ Backtest complete! Results saved to {output_dir}/")
        
        # Exit code based on promotion recommendation
        return 0 if criteria["recommend_promotion"] else 2
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
