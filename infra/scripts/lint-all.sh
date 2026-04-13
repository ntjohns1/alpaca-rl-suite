#!/usr/bin/env bash
# lint-all.sh — Run ruff lint checks across all Python services
#
# Usage:
#   ./infra/scripts/lint-all.sh          # Check all services
#   ./infra/scripts/lint-all.sh --fix    # Auto-fix where possible
#
# Requires: pip install ruff
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

FIX_FLAG=""
if [[ "${1:-}" == "--fix" ]]; then
  FIX_FLAG="--fix"
  echo "=== Running ruff with --fix ==="
else
  echo "=== Running ruff lint checks ==="
fi

# All Python service directories
SERVICES=(
  backtest
  dashboard
  dataset-builder
  feature-builder
  kaggle-orchestrator
  rl-infer
  rl-train
  temporal-worker
  web-ui
)

FAILED=()
for svc in "${SERVICES[@]}"; do
  SVC_DIR="$REPO_ROOT/services/$svc"
  if [ ! -d "$SVC_DIR" ]; then
    echo "[skip] $svc — directory not found"
    continue
  fi

  if ruff check $FIX_FLAG "$SVC_DIR" 2>/dev/null; then
    echo "[pass] $svc"
  else
    echo "[FAIL] $svc"
    FAILED+=("$svc")
  fi
done

echo ""
if [ ${#FAILED[@]} -gt 0 ]; then
  echo "=== FAILED: ${FAILED[*]} ==="
  echo "Run with --fix to auto-fix: ./infra/scripts/lint-all.sh --fix"
  exit 1
fi

echo "=== All ${#SERVICES[@]} services passed lint ==="
