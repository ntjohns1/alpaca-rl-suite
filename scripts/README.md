# Scripts

Standalone Python scripts for data management and model evaluation.

## backtest_policy.py

Backtest trained RL models on held-out test data (2024).

### Usage

```bash
# Basic backtest
python scripts/backtest_policy.py \
  --policy-path models/policy_20260303.zip \
  --symbol SPY

# Custom parameters
python scripts/backtest_policy.py \
  --policy-path models/policy_20260303.zip \
  --symbol SPY \
  --initial-capital 50000 \
  --trading-cost-bps 5 \
  --output-dir results/my_backtest/
```

### Requirements

Install dependencies:
```bash
pip install -r scripts/requirements.txt
```

Or install matplotlib if you already have the base dependencies:
```bash
pip install matplotlib seaborn
```

### What It Does

1. **Loads trained model** from `.zip` file (Stable-Baselines3 DQN)
2. **Fetches 2024 data** from PostgreSQL (held-out test set)
3. **Calculates features** matching `trading_env.py` (returns, RSI, MACD, etc.)
4. **Runs backtest** using sequential trading simulation
5. **Calculates metrics**: Sharpe ratio, max drawdown, win rate, profit factor, alpha
6. **Generates plots**: 
   - Equity curve (strategy vs buy-and-hold)
   - Drawdown chart
   - Position distribution
7. **Evaluates promotion criteria**:
   - ✅ Sharpe ratio > 1.0
   - ✅ Max drawdown < 15%
   - ✅ Win rate > 50%
   - ✅ Beats buy-and-hold (positive alpha)

### Output

**Console Summary:**
```
=== BACKTEST RESULTS ===
Symbol: SPY
Period: 2024-01-01 to 2024-12-31 (252 days)
Initial Capital: $100,000

PERFORMANCE METRICS
  Total Return:      12.3%
  Annualized Return: 12.3%
  Market Return:     8.5%
  Alpha:             3.8%

RISK METRICS
  Sharpe Ratio:      1.45
  Sortino Ratio:     2.12
  Max Drawdown:      -8.2%

TRADING METRICS
  Win Rate:          54.2%
  Profit Factor:     1.82
  Total Trades:      47

PROMOTION CRITERIA
  ✅ PASS: Sharpe Ratio > 1.0
  ✅ PASS: Max Drawdown < 15%
  ✅ PASS: Win Rate > 50%
  ✅ PASS: Beats Buy-and-Hold

✅ RECOMMENDATION: PROMOTE TO PRODUCTION
```

**Files Created:**
- `results/backtest_SPY_equity.png` - Equity curve with buy-and-hold comparison
- `results/backtest_SPY_drawdown.png` - Drawdown from peak
- `results/backtest_SPY_positions.png` - Position distribution
- `results/backtest_SPY_20260303.json` - Detailed metrics and equity curve data

### Exit Codes

- `0` - Success, model recommended for promotion
- `1` - Error occurred
- `2` - Success, but model NOT recommended for promotion

### Integration with Training Workflow

After downloading a model from Kaggle:

```bash
# 1. Download model from Kaggle notebook output
# (Manual step)

# 2. Run backtest
python scripts/backtest_policy.py \
  --policy-path models/kaggle/policy_20260303.zip \
  --symbol SPY \
  --output-dir results/

# 3. If promotion criteria met, upload to MinIO
if [ $? -eq 0 ]; then
  aws --endpoint-url http://localhost:9000 \
    s3 cp models/kaggle/policy_20260303.zip \
    s3://alpaca-rl-artifacts/models/production/spy_v1.zip
  
  echo "✅ Model promoted to production"
fi
```

### Testing

Run tests to validate the script:
```bash
pytest tests/test_backtest_script.py -v
```

## backfill_data.py

Backfill historical market data from Alpaca API.

### Usage

```bash
# Backfill daily data for indices
python scripts/backfill_data.py \
  --timeframe 1d \
  --start 2020-01-01 \
  --end 2024-12-31 \
  --groups indices

# Backfill specific symbols
python scripts/backfill_data.py \
  --timeframe 1d \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --symbols SPY QQQ IWM
```

See script help for more options:
```bash
python scripts/backfill_data.py --help
```

## Environment Variables

Scripts use these environment variables:

- `DATABASE_URL` - PostgreSQL connection string (required)
- `MARKET_INGEST_URL` - Market ingest service URL (for backfill_data.py)

Example:
```bash
export DATABASE_URL="postgresql://rl_user:rl_pass@localhost:5432/alpaca_rl"
export MARKET_INGEST_URL="http://localhost:3003"
```
