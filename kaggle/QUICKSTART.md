# Kaggle Integration - Quick Start Guide

Get GPU training running in 15 minutes!

## Prerequisites

- ✅ Alpaca RL Suite running locally
- ✅ Kaggle account (free)
- ✅ Data collected in PostgreSQL

## Step 1: Get Kaggle API Token (2 min)

**Using the new API Token method (Kaggle CLI >= 1.8.0)**

1. Go to https://www.kaggle.com/settings
2. Click on "Account" tab
3. Scroll to "API" section
4. Click "Generate API Token" (not "Create New API credentials")
5. Copy the generated token

```bash
# The token will look like: kaggle_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# Save it for the next step
```

**Note**: This uses the newer Bearer token authentication instead of the legacy username/key method.

## Step 2: Configure Environment (1 min)

Edit `.env` file:

```bash
# Add your Kaggle API Token
KAGGLE_API_TOKEN=kaggle_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

## Step 3: Deploy Orchestrator Service (2 min)

```bash
cd infra
docker-compose up -d --build kaggle-orchestrator

# Verify it's running
curl http://localhost:8011/kaggle/health
```

Expected response:
```json
{
  "status": "ok",
  "service": "kaggle-orchestrator",
  "kaggle_configured": true,
  "kaggle_cli_version": "1.8.0+",
  "auth_method": "API Token (Bearer)"
}
```

## Step 4: Create Kaggle Notebook (5 min)

1. Go to https://www.kaggle.com/code
2. Click "New Notebook"
3. Copy content from `kaggle/notebooks/alpaca-rl-training.ipynb`
4. Paste into Kaggle notebook
5. **Important**: Enable GPU
   - Click Settings (gear icon)
   - Accelerator → GPU T4 x2
   - Click "Save"
6. Save notebook as "alpaca-rl-training"

## Step 5: Run Your First Training (5 min)

### Option A: Automated (Recommended)

```bash
# Trigger training via API
curl -X POST http://localhost:8011/kaggle/train \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-first-training",
    "symbols": ["SPY"],
    "kernelSlug": "alpaca-rl-training",
    "totalTimesteps": 100000
  }'

# Get job ID from response, then monitor:
curl http://localhost:8011/kaggle/jobs/{jobId}
```

### Option B: Manual

```bash
# 1. Export dataset
cd /home/noslen/alpaca-rl-suite
python kaggle/scripts/export_dataset.py \
  --symbol SPY \
  --output /tmp/spy_data.csv

# 2. Upload to Kaggle
kaggle datasets create -p /tmp/spy_dataset

# 3. Go to Kaggle notebook and click "Run All"
```

## Step 6: Download Trained Model (2 min)

After training completes on Kaggle:

```bash
# Download and upload to MinIO
python kaggle/scripts/download_model.py \
  --kernel-slug alpaca-rl-training \
  --run-id $(date +%Y%m%d-%H%M%S)
```

## Verification

Check that everything works:

```bash
# 1. Orchestrator is running
curl http://localhost:8011/kaggle/health

# 2. Can export data
python kaggle/scripts/export_dataset.py --symbol SPY --output /tmp/test.csv

# 3. Kaggle CLI works
kaggle datasets list --user YOUR_USERNAME

# 4. MinIO is accessible
curl http://localhost:9000/minio/health/live
```

## What's Next?

### Automate Weekly Training

Add to crontab:

```bash
# Train every Sunday at 2 AM
0 2 * * 0 curl -X POST http://localhost:8011/kaggle/train \
  -H "Content-Type: application/json" \
  -d '{"name":"weekly-training","symbols":["SPY"],"totalTimesteps":500000}'
```

### Monitor Training

Check job status:

```bash
# List all jobs
curl http://localhost:8011/kaggle/jobs

# Get specific job
curl http://localhost:8011/kaggle/jobs/{jobId}
```

### Deploy Model for Trading

After downloading model:

```bash
# Promote model for inference
curl -X POST http://localhost:8004/rl/policies/{policyId}/promote

# Verify it's being used
curl http://localhost:8005/rl/infer/health
```

## Troubleshooting

### "Kaggle API Token not configured"

```bash
# Check your .env file has the token
grep KAGGLE_API_TOKEN .env

# Should show: KAGGLE_API_TOKEN=kaggle_xxxxx...
```

**Migration from Legacy Credentials**: If you previously used `kaggle.json`, you need to:
1. Generate a new API Token from Kaggle settings
2. Update `.env` to use `KAGGLE_API_TOKEN` instead of `KAGGLE_USERNAME`/`KAGGLE_KEY`
3. Rebuild the orchestrator: `docker-compose up -d --build kaggle-orchestrator`

### "Dataset upload failed"

```bash
# Install Kaggle CLI
pip install kaggle

# Test authentication
kaggle datasets list --user YOUR_USERNAME
```

### "GPU quota exceeded"

Kaggle provides 30 hours/week of GPU time. Check usage:
- Go to https://www.kaggle.com/settings
- Check "GPU Quota" section
- Resets every Monday

### "Model download failed"

```bash
# List available outputs
kaggle kernels output YOUR_USERNAME/alpaca-rl-training --list

# Download manually
kaggle kernels output YOUR_USERNAME/alpaca-rl-training -p /tmp/output
```

## Cost Breakdown

| Component | Cost | Notes |
|-----------|------|-------|
| Kaggle GPU | **$0** | 30 hrs/week free |
| Home Lab Storage | **$0** | Use existing hardware |
| Data Transfer | **$0** | Minimal bandwidth |
| **Total** | **$0/month** | 🎉 |

## Performance Expectations

- **Training Time**: 30-60 min per 500k timesteps
- **GPU Speedup**: ~10-20x faster than CPU
- **Models per Week**: 30-60 (with 30hr quota)
- **Model Size**: ~10-50 MB each

## Support

- 📖 Full docs: `kaggle/README.md`
- 🐛 Issues: Check logs with `docker-compose logs kaggle-orchestrator`
- 💬 Kaggle help: https://www.kaggle.com/discussions

## Success! 🚀

You now have:
- ✅ Free GPU training on Kaggle
- ✅ Automated dataset sync
- ✅ Model deployment pipeline
- ✅ Scalable RL training workflow

Happy training!
