# Kaggle GPU Training Integration

This directory contains everything needed to train RL models on Kaggle's free GPU resources and integrate them back into your home lab.

## Overview

**Problem**: Training RL models requires GPU resources that you don't have locally.

**Solution**: Use Kaggle's free 30 hours/week of GPU time for training, while keeping data collection and trading execution in your home lab.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Home Lab                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Postgres   │  │    MinIO     │  │  Orchestrator│      │
│  │  (Bar Data)  │  │  (Models)    │  │   Service    │      │
│  └──────┬───────┘  └──────▲───────┘  └──────┬───────┘      │
│         │                  │                  │              │
└─────────┼──────────────────┼──────────────────┼──────────────┘
          │                  │                  │
          │ 1. Export        │ 4. Upload        │ 2. Trigger
          │    Dataset       │    Model         │    Training
          │                  │                  │
          ▼                  │                  ▼
┌─────────────────────────────────────────────────────────────┐
│                        Kaggle                                │
│  ┌──────────────┐         ┌──────────────┐                  │
│  │   Dataset    │────────▶│   Notebook   │                  │
│  │   (CSV)      │         │  (GPU Train) │                  │
│  └──────────────┘         └──────┬───────┘                  │
│                                   │ 3. Save Model            │
│                                   ▼                          │
│                          ┌──────────────┐                    │
│                          │    Output    │                    │
│                          │  (Model.zip) │                    │
│                          └──────────────┘                    │
└─────────────────────────────────────────────────────────────┘
```

## Workflow

### Semi-Automatic Mode (Recommended)

1. **Trigger Training** (Automated)
   ```bash
   curl -X POST http://localhost:8011/kaggle/train \
     -H "Content-Type: application/json" \
     -d '{
       "name": "spy-training-run-1",
       "symbols": ["SPY"],
       "kernelSlug": "alpaca-rl-training",
       "totalTimesteps": 500000
     }'
   ```

2. **Monitor on Kaggle** (Manual)
   - Go to https://www.kaggle.com/code/YOUR_USERNAME/alpaca-rl-training
   - Check training progress
   - Wait for completion (~30-60 minutes with GPU)

3. **Download Model** (Semi-Automated)
   ```bash
   python kaggle/scripts/download_model.py \
     --kernel-slug alpaca-rl-training \
     --run-id 20260301-123456
   ```

4. **Deploy for Inference** (Automated)
   - Model is automatically available in MinIO
   - Use rl-infer service to load and run

### Manual Mode (Full Control)

1. **Export Dataset**
   ```bash
   python kaggle/scripts/export_dataset.py \
     --symbol SPY \
     --output spy_data.csv
   ```

2. **Upload to Kaggle**
   - Go to https://www.kaggle.com/datasets
   - Click "New Dataset"
   - Upload `spy_data.csv`
   - Note the dataset slug

3. **Create/Update Notebook**
   - Copy `kaggle/notebooks/alpaca-rl-training.ipynb` to Kaggle
   - Enable GPU in settings
   - Attach your dataset
   - Set MinIO credentials in Kaggle Secrets (optional)

4. **Run Training**
   - Click "Run All"
   - Monitor progress
   - Wait for completion

5. **Download Model**
   - Option A: Download from Kaggle notebook output
   - Option B: If MinIO credentials set, model auto-uploads
   - Option C: Use download script (see above)

## Setup

### 1. Kaggle API Token (CLI >= 1.8.0)

**Important**: We use the newer API Token method (not legacy credentials).

Get your API token from https://www.kaggle.com/settings

1. Click "Account" tab
2. Scroll to "API" section  
3. Click "Generate API Token" (not "Create New API credentials")
4. Copy the generated token (format: `kaggle_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx`)

```bash
# Add to your .env file
echo "KAGGLE_API_TOKEN=kaggle_your_token_here" >> .env
```

**Why API Token?**
- ✅ Recommended by Kaggle for CLI >= 1.8.0
- ✅ More secure (Bearer token authentication)
- ✅ Easier to rotate and manage
- ✅ Better integration with modern tools

### 2. Environment Variables

Add to your `.env` file:

```bash
# Kaggle Configuration (API Token method - CLI >= 1.8.0)
KAGGLE_API_TOKEN=kaggle_your_token_here

# Kaggle Orchestrator
KAGGLE_ORCHESTRATOR_PORT=8011
```

### 3. Deploy Orchestrator Service

The orchestrator service is included in docker-compose.yml:

```bash
cd infra
docker-compose up -d kaggle-orchestrator
```

### 4. Create Kaggle Notebook

1. Go to https://www.kaggle.com/code
2. Click "New Notebook"
3. Copy content from `kaggle/notebooks/alpaca-rl-training.ipynb`
4. Save as "alpaca-rl-training"
5. Enable GPU: Settings → Accelerator → GPU T4 x2

### 5. (Optional) Configure MinIO Access from Kaggle

To enable automatic model upload from Kaggle:

1. Go to your Kaggle notebook
2. Add Secrets (right panel):
   - `S3_ENDPOINT`: Your public IP or domain (e.g., `http://YOUR_IP:9000`)
   - `S3_ACCESS_KEY`: `minioadmin`
   - `S3_SECRET_KEY`: `minioadmin`
   - `S3_BUCKET`: `alpaca-rl-artifacts`

**Security Note**: For production, use a reverse proxy with HTTPS and create dedicated MinIO credentials.

## API Reference

### Kaggle Orchestrator Service

**Base URL**: `http://localhost:8011`

#### Start Training

```bash
POST /kaggle/train
Content-Type: application/json

{
  "name": "training-run-name",
  "symbols": ["SPY"],
  "kernelSlug": "alpaca-rl-training",
  "datasetSlug": "alpaca-rl-spy",  # optional, auto-generated
  "totalTimesteps": 500000,
  "tradingDays": 252,
  "tradingCostBps": 10,
  "learningRate": 0.0001,
  "batchSize": 256,
  "architecture": [256, 256]
}
```

Response:
```json
{
  "jobId": "uuid",
  "status": "preparing",
  "name": "training-run-name",
  "message": "Kaggle training job initiated..."
}
```

#### Get Job Status

```bash
GET /kaggle/jobs/{jobId}
```

Response:
```json
{
  "id": "uuid",
  "name": "training-run-name",
  "status": "training_on_kaggle",
  "metadata": {
    "kaggle_url": "https://www.kaggle.com/code/username/kernel",
    "dataset_info": {...}
  },
  "created_at": "2026-03-01T12:00:00Z"
}
```

Status values:
- `preparing`: Exporting dataset
- `uploading_dataset`: Uploading to Kaggle
- `triggering_kernel`: Starting notebook
- `training_on_kaggle`: Training in progress (check Kaggle)
- `downloading_model`: Retrieving trained model
- `uploading_model`: Uploading to MinIO
- `completed`: Ready for inference
- `failed`: Error occurred

#### Complete Job (Webhook)

```bash
POST /kaggle/jobs/{jobId}/complete?kernel_slug=alpaca-rl-training
```

Call this after training completes on Kaggle to download the model.

#### List Jobs

```bash
GET /kaggle/jobs?limit=50
```

## Cost Analysis

### Kaggle Free Tier
- **GPU Time**: 30 hours/week
- **GPU Type**: NVIDIA Tesla T4 (16GB VRAM)
- **Training Time**: ~30-60 minutes per run (500k timesteps)
- **Runs per Week**: ~30-60 runs

### Home Lab Costs
- **Data Storage**: Minimal (PostgreSQL)
- **Model Storage**: ~10-50 MB per model (MinIO)
- **Inference**: CPU-only (fast enough for trading)

**Total Cost**: $0/month for training! 🎉

## Troubleshooting

### Dataset Upload Fails

```bash
# Check Kaggle CLI is installed
kaggle --version

# Test authentication
kaggle datasets list --user YOUR_USERNAME
```

### Kernel Won't Start

1. Check GPU is enabled in notebook settings
2. Verify dataset is attached
3. Check Kaggle quota (30hrs/week limit)

### Model Download Fails

```bash
# List kernel outputs
kaggle kernels output YOUR_USERNAME/alpaca-rl-training --list

# Download manually
kaggle kernels output YOUR_USERNAME/alpaca-rl-training -p /tmp/kaggle_output
```

### MinIO Upload from Kaggle Fails

1. Verify your home lab is accessible from internet
2. Check firewall allows port 9000
3. Consider using ngrok or Cloudflare Tunnel for secure access
4. Alternatively, download model manually and upload locally

## Advanced: Scheduled Training

Set up cron job to trigger weekly training:

```bash
# Add to crontab
0 2 * * 0 curl -X POST http://localhost:8011/kaggle/train \
  -H "Content-Type: application/json" \
  -d '{"name":"weekly-spy-training","symbols":["SPY"],"totalTimesteps":500000}'
```

## Security Best Practices

1. **Never commit Kaggle credentials** to git
2. **Use environment variables** for all secrets
3. **Restrict MinIO access** with firewall rules
4. **Use HTTPS** for public-facing endpoints
5. **Rotate credentials** regularly
6. **Monitor Kaggle usage** to avoid quota exhaustion

## Next Steps

1. ✅ Set up Kaggle API credentials
2. ✅ Deploy orchestrator service
3. ✅ Create Kaggle notebook
4. ✅ Run first training job
5. ✅ Download and deploy model
6. ✅ Verify inference works
7. 🚀 Automate with webhooks/cron

## Resources

- [Kaggle API Documentation](https://github.com/Kaggle/kaggle-api)
- [Stable-Baselines3 Documentation](https://stable-baselines3.readthedocs.io/)
- [Gymnasium Documentation](https://gymnasium.farama.org/)

## Support

For issues or questions:
1. Check logs: `docker-compose logs kaggle-orchestrator`
2. Check Kaggle notebook output
3. Review this documentation
4. Check MinIO logs: `docker-compose logs minio`
