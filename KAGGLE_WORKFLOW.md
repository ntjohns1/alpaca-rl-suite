# Complete Kaggle Training Workflow

## Overview

This document describes the complete end-to-end workflow for training RL models on Kaggle GPU and deploying them to production.

## Prerequisites

✅ **Completed:**
- Kaggle CLI installed and authenticated (`~/.config/kaggle/kaggle.json`)
- Existing Kaggle kernel: `nelsonjohns/alpaca-rl-training`
- PostgreSQL database with historical market data
- Backtest script ready (`scripts/backtest_policy.py`)
- MinIO artifact storage running

## Workflow Steps

### 1. Export Training Data

Export data from your PostgreSQL database to CSV for Kaggle:

```bash
# Export data for a specific symbol
python kaggle/scripts/export_dataset.py \
  --symbol SPY \
  --start-date 2020-01-01 \
  --end-date 2023-12-31 \
  --output-dir kaggle/datasets/spy-training

# This creates:
# - kaggle/datasets/spy-training/bar_1d.csv
# - kaggle/datasets/spy-training/dataset-metadata.json
```

### 2. Upload Dataset to Kaggle

```bash
# Create new dataset
cd kaggle/datasets/spy-training
kaggle datasets create

# Or update existing dataset
kaggle datasets version -m "Updated training data"
```

**Output:** Dataset URL like `https://www.kaggle.com/datasets/nelsonjohns/alpaca-rl-spy-20260303`

### 3. Trigger Training (Semi-Automated)

Use the automation script to update the kernel with the new dataset:

```bash
# Update kernel to use new dataset
./scripts/trigger_kaggle_training.sh alpaca-rl-spy-20260303
```

This script:
- Creates kernel metadata with the dataset attached
- Pushes the kernel update via `kaggle kernels push`
- Provides next steps

**Manual step required:**
1. Go to https://www.kaggle.com/code/nelsonjohns/alpaca-rl-training
2. Verify dataset is attached
3. Enable GPU: Settings → Accelerator → GPU T4 x2
4. Click **"Run All"**

### 4. Monitor Training

Watch the notebook execution in real-time:
- Training progress bars
- Episode rewards
- Loss curves
- Final metrics

**Training typically takes:** 30-60 minutes for 1M timesteps on GPU T4 x2

### 5. Download Trained Model

After training completes:

```bash
# Download from Kaggle notebook output
# Files created by notebook:
# - policy_YYYYMMDD-HHMMSS.zip (trained model)
# - metrics_YYYYMMDD-HHMMSS.json (training metrics)

# Save to local models directory
mkdir -p models/kaggle
mv ~/Downloads/policy_*.zip models/kaggle/
mv ~/Downloads/metrics_*.json models/kaggle/
```

### 6. Backtest on Held-Out Data

Evaluate the model on 2024 test data:

```bash
python scripts/backtest_policy.py \
  --policy-path models/kaggle/policy_20260303-013728.zip \
  --symbol SPY \
  --database-url "postgresql://rl_user:rl_pass@localhost:5432/alpaca_rl" \
  --output-dir results/
```

**Output:**
- Console summary with promotion criteria pass/fail
- 3 PNG charts (equity, drawdown, positions)
- JSON report with full metrics
- Exit code: 0 (promote), 1 (error), 2 (don't promote)

### 7. Review Results

Check the backtest results:

```bash
# View charts
open results/backtest_SPY_equity.png
open results/backtest_SPY_drawdown.png
open results/backtest_SPY_positions.png

# View detailed metrics
cat results/backtest_SPY_20260303.json | jq .
```

**Promotion Criteria:**
- ✅ Sharpe ratio > 1.0
- ✅ Max drawdown < 15%
- ✅ Win rate > 50%
- ✅ Beats buy-and-hold (positive alpha)

### 8. Promote to Production (If Criteria Met)

If backtest passes all criteria:

```bash
# Upload to MinIO
aws --endpoint-url http://localhost:9000 \
  s3 cp models/kaggle/policy_20260303-013728.zip \
  s3://alpaca-rl-artifacts/models/production/spy_v1.zip

# Register with rl-train service
curl -X POST http://localhost:8004/rl/policies \
  -H "Content-Type: application/json" \
  -d '{
    "name": "SPY Baseline v1",
    "symbol": "SPY",
    "s3_key": "models/production/spy_v1.zip",
    "metrics": {
      "sharpe_ratio": 1.45,
      "max_drawdown": 0.0823,
      "win_rate": 0.5426,
      "alpha": 0.0507
    },
    "backtest_date": "2024-03-03"
  }'

# Promote to active
curl -X POST http://localhost:8004/rl/policies/{policyId}/promote
```

### 9. Verify Deployment

```bash
# Check inference service
curl http://localhost:8005/rl/infer/health

# Get current policy
curl http://localhost:8005/rl/infer/policy
```

## Automation Status

### ✅ **FULLY AUTOMATED END-TO-END!**

The complete workflow is now automated using `kaggle kernels push` which:
1. Updates kernel metadata with new dataset
2. **Automatically triggers kernel execution** (runs the notebook)
3. Polls for completion
4. Downloads trained model
5. Runs backtest
6. Evaluates promotion criteria

**One-command workflow:**
```bash
./scripts/kaggle_train_and_download.sh alpaca-rl-spy-20260303 SPY
```

This single command:
- ✅ Pushes kernel to Kaggle (triggers training)
- ✅ Waits for training to complete (polls status)
- ✅ Downloads trained model automatically
- ✅ Runs backtest on 2024 test data
- ✅ Evaluates promotion criteria
- ✅ Provides next steps (upload to production if criteria met)

### 📋 Manual Steps (Optional)
1. Review backtest visualizations (charts)
2. Approve production promotion (if criteria met)
3. Monitor training progress in Kaggle UI (optional)

## Scripts Reference

| Script | Purpose |
|--------|---------|
| `kaggle/scripts/export_dataset.py` | Export PostgreSQL data to CSV |
| `scripts/kaggle_train_and_download.sh` | **🚀 FULL AUTOMATION** - Train, download, backtest |
| `scripts/trigger_kaggle_training.sh` | Update kernel and trigger training only |
| `scripts/backtest_policy.py` | Backtest trained model on 2024 data |
| `scripts/get_kaggle_kernel_id.py` | Get kernel metadata (debugging) |

## Environment Variables

Required in `.env`:

```bash
# Database
DATABASE_URL=postgresql://rl_user:rl_pass@localhost:5432/alpaca_rl

# Kaggle (for CLI authentication)
KAGGLE_USERNAME=nelsonjohns
KAGGLE_API_TOKEN=KGAT_xxx...

# MinIO
S3_ENDPOINT=http://localhost:9000
S3_BUCKET=alpaca-rl-artifacts
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
```

Kaggle CLI also needs `~/.config/kaggle/kaggle.json`:
```json
{
  "username": "nelsonjohns",
  "key": "KGAT_xxx..."
}
```

## Troubleshooting

### Kaggle CLI Authentication Error

```bash
# Error: Could not find kaggle.json
# Solution: Create ~/.config/kaggle/kaggle.json with your credentials
mkdir -p ~/.config/kaggle
cat > ~/.config/kaggle/kaggle.json <<EOF
{
  "username": "nelsonjohns",
  "key": "KGAT_xxx..."
}
EOF
chmod 600 ~/.config/kaggle/kaggle.json
```

### Kernel Not Found

```bash
# List your kernels
kaggle kernels list --user nelsonjohns

# If kernel doesn't exist, create it
cd kaggle/kernel-setup
kaggle kernels push
```

### Backtest Fails - Missing Dependencies

```bash
# Install in your conda environment
conda activate alpaca
pip install stable-baselines3 matplotlib seaborn
conda install psycopg2 ta
pip install --upgrade numpy  # Need numpy 2.x
```

### Model Won't Load - Numpy Version Mismatch

```bash
# Upgrade numpy to 2.x
pip install --upgrade numpy

# Verify
python -c "import numpy; print(numpy.__version__)"  # Should be 2.x
```

## Performance Expectations

### Training Time (Kaggle GPU T4 x2)
- 500K timesteps: ~15 minutes
- 1M timesteps: ~30 minutes
- 2M timesteps: ~60 minutes

### Backtest Time (Local CPU)
- 250 days of data: ~10 seconds
- Includes feature calculation, inference, and visualization

### Dataset Sizes
- 1 year daily data (1 symbol): ~100 KB
- 4 years daily data (1 symbol): ~400 KB
- Training dataset with features: ~1 MB

## Next Steps

1. **Iterate on hyperparameters** - Your first model failed promotion
   - Increase training timesteps (try 2M+)
   - Adjust learning rate
   - Modify cost parameters
   - Try different reward functions

2. **Train on multiple symbols** - Diversify strategy
   - SPY (S&P 500)
   - QQQ (Nasdaq)
   - IWM (Russell 2000)

3. **Implement ensemble** - Combine multiple models
   - Train 3-5 models with different seeds
   - Average predictions
   - Improves robustness

4. **Set up CI/CD** - Automate the workflow
   - GitHub Actions to trigger training
   - Automatic backtesting on model download
   - Slack notifications for results

## Resources

- **Kaggle Kernel:** https://www.kaggle.com/code/nelsonjohns/alpaca-rl-training
- **Kaggle API Docs:** https://github.com/Kaggle/kaggle-api
- **Stable-Baselines3 Docs:** https://stable-baselines3.readthedocs.io/
- **Project README:** `README.md`
- **Backtest Implementation:** `BACKTEST_IMPLEMENTATION.md`
