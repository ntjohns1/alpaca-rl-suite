#!/bin/bash
# ⚠️  DEPRECATED — Use the unified CLI or Kaggle Orchestrator service instead.
#
#   CLI:     alpaca-rl train --mode kaggle --symbol SPY --timesteps 500000
#   API:     POST http://localhost:8011/kaggle/train
#
# The kaggle-orchestrator service now handles dataset upload and kernel
# triggering automatically. This script is kept for reference only.
# ─────────────────────────────────────────────────────────────────────────
#
# Trigger Kaggle training by updating kernel with new dataset
#
# Usage: ./trigger_kaggle_training.sh <dataset-slug>
# Example: ./trigger_kaggle_training.sh alpaca-rl-spy-20260303

set -e

echo "⚠️  WARNING: This script is deprecated. Use 'alpaca-rl train --mode kaggle' instead."
echo ""

DATASET_SLUG=$1
KERNEL_SLUG="nelsonjohns/alpaca-rl-training"

if [ -z "$DATASET_SLUG" ]; then
    echo "❌ Error: Dataset slug required"
    echo "Usage: $0 <dataset-slug>"
    echo "Example: $0 alpaca-rl-spy-20260303"
    exit 1
fi

echo "🔧 Preparing kernel update for dataset: $DATASET_SLUG"

# Create temporary directory for kernel files
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

# Copy notebook to temp directory
cp kaggle/notebooks/alpaca-rl-training.ipynb "$TEMP_DIR/"

# Create kernel metadata with dataset source
cat > "$TEMP_DIR/kernel-metadata.json" <<EOF
{
  "id": "$KERNEL_SLUG",
  "title": "Alpaca RL Training",
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

echo "📤 Pushing kernel update to Kaggle..."
echo "   This will update the kernel AND trigger execution automatically"
cd "$TEMP_DIR"
kaggle kernels push

echo ""
echo "✅ Kernel pushed and execution triggered!"
echo ""
echo "� Monitor training progress:"
echo "   https://www.kaggle.com/code/$KERNEL_SLUG"
echo ""
echo "📋 Check status:"
echo "   kaggle kernels status $KERNEL_SLUG"
echo ""
echo "📥 Download output when complete:"
echo "   kaggle kernels output $KERNEL_SLUG -p models/kaggle/"
echo ""
echo "💡 Training typically takes 30-60 minutes on GPU T4 x2"
