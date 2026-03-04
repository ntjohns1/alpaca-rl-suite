#!/bin/bash
# Complete automated Kaggle training workflow
# 
# This script:
# 1. Updates kernel with new dataset
# 2. Triggers training automatically via 'kaggle kernels push'
# 3. Polls for completion
# 4. Downloads trained model
# 5. Runs backtest
# 6. Reports results
#
# Usage: ./kaggle_train_and_download.sh <dataset-slug> <symbol>
# Example: ./kaggle_train_and_download.sh alpaca-rl-spy-20260303 SPY

set -e

# Use full path to kaggle CLI
KAGGLE_CLI="${KAGGLE_CLI:-/home/noslen/anaconda3/envs/alpaca/bin/kaggle}"

DATASET_SLUG=$1
SYMBOL=$2
KERNEL_SLUG="nelsonjohns/alpaca-rl-training"
DATABASE_URL="${DATABASE_URL:-postgresql://rl_user:rl_pass@localhost:5432/alpaca_rl}"

if [ -z "$DATASET_SLUG" ] || [ -z "$SYMBOL" ]; then
    echo "❌ Error: Dataset slug and symbol required"
    echo "Usage: $0 <dataset-slug> <symbol>"
    echo "Example: $0 alpaca-rl-spy-20260303 SPY"
    exit 1
fi

echo "🚀 Starting automated Kaggle training workflow"
echo "   Dataset: $DATASET_SLUG"
echo "   Symbol: $SYMBOL"
echo ""

# Step 1: Push kernel with dataset (triggers execution)
echo "📤 Step 1/5: Pushing kernel to Kaggle (triggers training)..."

TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

cp kaggle/notebooks/alpaca-rl-training.ipynb "$TEMP_DIR/"

cat > "$TEMP_DIR/kernel-metadata.json" <<EOF
{
  "id": "$KERNEL_SLUG",
  "title": "Alpaca RL Training - $SYMBOL",
  "code_file": "alpaca-rl-training.ipynb",
  "language": "python",
  "kernel_type": "notebook",
  "is_private": "true",
  "enable_gpu": "true",
  "enable_tpu": "false",
  "enable_internet": "true",
  "dataset_sources": ["nelsonjohns/$DATASET_SLUG"],
  "competition_sources": [],
  "kernel_sources": [],
  "model_sources": []
}
EOF

cd "$TEMP_DIR"
$KAGGLE_CLI kernels push

echo "✅ Kernel pushed and training started!"
echo ""

# Step 2: Poll for completion
echo "⏳ Step 2/5: Waiting for training to complete..."
echo "   Monitor at: https://www.kaggle.com/code/$KERNEL_SLUG"
echo ""

MAX_WAIT=7200  # 2 hours
POLL_INTERVAL=60  # 1 minute
ELAPSED=0

while [ $ELAPSED -lt $MAX_WAIT ]; do
    STATUS=$($KAGGLE_CLI kernels status $KERNEL_SLUG 2>&1 || echo "error")
    
    if echo "$STATUS" | grep -q "complete"; then
        echo "✅ Training complete!"
        break
    elif echo "$STATUS" | grep -q "error\|failed"; then
        echo "❌ Training failed!"
        echo "$STATUS"
        exit 1
    elif echo "$STATUS" | grep -q "running"; then
        echo "   Still running... ($ELAPSED seconds elapsed)"
    fi
    
    sleep $POLL_INTERVAL
    ELAPSED=$((ELAPSED + POLL_INTERVAL))
done

if [ $ELAPSED -ge $MAX_WAIT ]; then
    echo "⚠️  Timeout waiting for training (2 hours)"
    echo "   Check status manually: $KAGGLE_CLI kernels status $KERNEL_SLUG"
    exit 1
fi

echo ""

# Step 3: Download output
echo "📥 Step 3/5: Downloading trained model..."

OUTPUT_DIR="models/kaggle/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUTPUT_DIR"

$KAGGLE_CLI kernels output $KERNEL_SLUG -p "$OUTPUT_DIR"

echo "✅ Model downloaded to: $OUTPUT_DIR"
echo ""

# Step 4: Find the policy file
POLICY_FILE=$(find "$OUTPUT_DIR" -name "policy_*.zip" | head -1)

if [ -z "$POLICY_FILE" ]; then
    echo "❌ No policy file found in output"
    ls -la "$OUTPUT_DIR"
    exit 1
fi

echo "📦 Found policy: $POLICY_FILE"
echo ""

# Step 5: Run backtest
echo "📊 Step 4/5: Running backtest on 2024 test data..."

python scripts/backtest_policy.py \
  --policy-path "$POLICY_FILE" \
  --symbol "$SYMBOL" \
  --database-url "$DATABASE_URL" \
  --output-dir "results/$(basename $OUTPUT_DIR)"

BACKTEST_EXIT=$?

echo ""
echo "============================================================"
echo "                  WORKFLOW COMPLETE"
echo "============================================================"
echo ""
echo "📁 Model location: $POLICY_FILE"
echo "📊 Results: results/$(basename $OUTPUT_DIR)/"
echo ""

if [ $BACKTEST_EXIT -eq 0 ]; then
    echo "✅ PROMOTION RECOMMENDED"
    echo ""
    echo "Next steps:"
    echo "  1. Review charts in results/$(basename $OUTPUT_DIR)/"
    echo "  2. Upload to production:"
    echo "     aws --endpoint-url http://localhost:9000 \\"
    echo "       s3 cp $POLICY_FILE \\"
    echo "       s3://alpaca-rl-artifacts/models/production/${SYMBOL}_$(date +%Y%m%d).zip"
    exit 0
elif [ $BACKTEST_EXIT -eq 2 ]; then
    echo "❌ PROMOTION NOT RECOMMENDED"
    echo ""
    echo "Model did not meet promotion criteria."
    echo "Review results and iterate on hyperparameters."
    exit 2
else
    echo "❌ BACKTEST ERROR"
    exit 1
fi
