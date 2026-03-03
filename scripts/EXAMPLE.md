# Backtest Script Example

## Complete Workflow: From Kaggle Training to Production

### Step 1: Train Model on Kaggle

1. Trigger training via orchestrator:
```bash
curl -X POST http://localhost:8011/kaggle/train \
  -H "Content-Type: application/json" \
  -d '{
    "name": "spy-baseline-v1",
    "symbols": ["SPY"],
    "kernelSlug": "alpaca-rl-training",
    "totalTimesteps": 1000000
  }'
```

2. Get job ID and wait for completion
3. Manually run the Kaggle notebook (click "Run All")
4. Download trained model from Kaggle output: `policy_YYYYMMDD-HHMMSS.zip`

### Step 2: Backtest on Held-Out Data

Save the downloaded model to `models/kaggle/` directory:

```bash
# Create models directory
mkdir -p models/kaggle

# Move downloaded model
mv ~/Downloads/policy_20260303-012345.zip models/kaggle/

# Run backtest
python scripts/backtest_policy.py \
  --policy-path models/kaggle/policy_20260303-012345.zip \
  --symbol SPY \
  --initial-capital 100000 \
  --output-dir results/spy_baseline_v1/
```

### Step 3: Review Results

**Console Output:**
```
📊 Loading data for SPY (2024-01-01 to 2024-12-31)...
  ✓ Loaded 252 bars
  Date range: 2024-01-02 to 2024-12-31

🔧 Calculating features...
  ✓ Calculated features (231 valid rows after dropping NaN)

🤖 Loading policy from models/kaggle/policy_20260303-012345.zip...
  ✓ Policy loaded

📈 Running backtest...
  Initial capital: $100,000
  Trading cost: 10 bps
  Time cost: 1 bps
  ✓ Backtest complete (231 days, 47 trades)

📊 Creating visualizations...
  ✓ Saved results/spy_baseline_v1/backtest_SPY_equity.png
  ✓ Saved results/spy_baseline_v1/backtest_SPY_drawdown.png
  ✓ Saved results/spy_baseline_v1/backtest_SPY_positions.png

============================================================
                    BACKTEST RESULTS
============================================================

Symbol: SPY
Period: 2024-01-01 to 2024-12-31 (231 days)
Initial Capital: $100,000

------------------------------------------------------------
PERFORMANCE METRICS
------------------------------------------------------------
  Total Return:      12.34%
  Annualized Return: 13.52%
  Market Return:      8.45%
  Alpha:              5.07%

------------------------------------------------------------
RISK METRICS
------------------------------------------------------------
  Sharpe Ratio:       1.45
  Sortino Ratio:      2.12
  Max Drawdown:       8.23%

------------------------------------------------------------
TRADING METRICS
------------------------------------------------------------
  Win Rate:          54.26%
  Profit Factor:      1.82
  Total Trades:         47

------------------------------------------------------------
PROMOTION CRITERIA
------------------------------------------------------------
  ✅ PASS: Sharpe Ratio > 1.0
  ✅ PASS: Max Drawdown < 15%
  ✅ PASS: Win Rate > 50%
  ✅ PASS: Beats Buy-and-Hold

============================================================
        ✅ RECOMMENDATION: PROMOTE TO PRODUCTION
============================================================

💾 Saved detailed report: results/spy_baseline_v1/backtest_SPY_20260303.json

✅ Backtest complete! Results saved to results/spy_baseline_v1/
```

**Generated Files:**
- `results/spy_baseline_v1/backtest_SPY_equity.png` - Shows strategy outperforming buy-and-hold
- `results/spy_baseline_v1/backtest_SPY_drawdown.png` - Max drawdown of 8.23%
- `results/spy_baseline_v1/backtest_SPY_positions.png` - Position distribution
- `results/spy_baseline_v1/backtest_SPY_20260303.json` - Full metrics and equity curve

### Step 4: Promote to Production (If Criteria Met)

Since all promotion criteria passed, upload to MinIO:

```bash
# Upload model to production bucket
aws --endpoint-url http://localhost:9000 \
  s3 cp models/kaggle/policy_20260303-012345.zip \
  s3://alpaca-rl-artifacts/models/production/spy_baseline_v1.zip

# Register in database (via rl-train service)
curl -X POST http://localhost:8004/rl/policies \
  -H "Content-Type: application/json" \
  -d '{
    "name": "SPY Baseline v1",
    "symbol": "SPY",
    "s3_key": "models/production/spy_baseline_v1.zip",
    "metrics": {
      "sharpe_ratio": 1.45,
      "max_drawdown": 0.0823,
      "win_rate": 0.5426,
      "alpha": 0.0507,
      "total_return": 0.1234
    },
    "backtest_date": "2024-03-03",
    "test_period": "2024-01-01 to 2024-12-31"
  }'

# Get policy ID from response, then promote
curl -X POST http://localhost:8004/rl/policies/{policyId}/promote

# Verify deployment
curl http://localhost:8005/rl/infer/health
```

### Step 5: Monitor Performance

After promotion, monitor the model in production:

```bash
# Check inference service status
curl http://localhost:8005/rl/infer/health

# Get current policy info
curl http://localhost:8005/rl/infer/policy

# Monitor trading activity (if live)
curl http://localhost:8005/rl/infer/stats
```

## Example: Model That Fails Promotion

If a model doesn't meet criteria:

```bash
python scripts/backtest_policy.py \
  --policy-path models/kaggle/policy_bad.zip \
  --symbol SPY
```

**Output:**
```
============================================================
PROMOTION CRITERIA
------------------------------------------------------------
  ❌ FAIL: Sharpe Ratio > 1.0 (got 0.82)
  ✅ PASS: Max Drawdown < 15%
  ✅ PASS: Win Rate > 50%
  ❌ FAIL: Beats Buy-and-Hold (alpha: -0.02)

============================================================
        ❌ RECOMMENDATION: DO NOT PROMOTE
============================================================
```

**Exit code: 2** (indicates success but no promotion)

**Action:** Don't promote. Iterate on training:
- Try different hyperparameters
- Add more training data
- Adjust cost parameters
- Test different architectures

## Automation Script

Create `scripts/auto_promote.sh`:

```bash
#!/bin/bash
# Automated model evaluation and promotion

MODEL_PATH=$1
SYMBOL=$2

if [ -z "$MODEL_PATH" ] || [ -z "$SYMBOL" ]; then
    echo "Usage: $0 <model_path> <symbol>"
    exit 1
fi

echo "🔍 Backtesting model: $MODEL_PATH"

# Run backtest
python scripts/backtest_policy.py \
  --policy-path "$MODEL_PATH" \
  --symbol "$SYMBOL" \
  --output-dir "results/$(basename $MODEL_PATH .zip)/"

# Check exit code
if [ $? -eq 0 ]; then
    echo "✅ Model passed all criteria!"
    echo "📤 Uploading to production..."
    
    # Upload to MinIO
    aws --endpoint-url http://localhost:9000 \
      s3 cp "$MODEL_PATH" \
      "s3://alpaca-rl-artifacts/models/production/${SYMBOL}_$(date +%Y%m%d).zip"
    
    echo "✅ Model promoted to production!"
else
    echo "❌ Model did not meet promotion criteria"
    echo "📊 Review results in results/ directory"
    exit 1
fi
```

Usage:
```bash
chmod +x scripts/auto_promote.sh
./scripts/auto_promote.sh models/kaggle/policy_20260303.zip SPY
```

## Tips

1. **Always backtest before promoting** - Never deploy untested models
2. **Review visualizations** - Charts reveal issues metrics might miss
3. **Compare to baseline** - Buy-and-hold comparison is essential
4. **Track over time** - Keep backtest results for model comparison
5. **Test on multiple symbols** - Ensure generalization
6. **Document decisions** - Save backtest reports with model versions
