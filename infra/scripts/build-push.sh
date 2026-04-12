#!/usr/bin/env bash
# build-push.sh — Build and push service images to GHCR
#
# Usage:
#   ./build-push.sh              # Build & push all services
#   ./build-push.sh auth orders  # Build & push specific services
#   ./build-push.sh --build-only # Build without pushing
#
# Requires: GITHUB_TOKEN env var with write:packages scope
set -euo pipefail

REGISTRY="ghcr.io/ntjohns1/alpaca-rl-suite"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
GIT_SHA=$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo "unknown")

BUILD_ONLY=false

# All services with their Dockerfile paths (relative to repo root)
declare -A SERVICES=(
  # Node.js services (build context = repo root)
  [auth]="services/auth/Dockerfile"
  [alpaca-adapter]="services/alpaca-adapter/Dockerfile"
  [market-ingest]="services/market-ingest/Dockerfile"
  [orders]="services/orders/Dockerfile"
  [risk]="services/risk/Dockerfile"
  [portfolio]="services/portfolio/Dockerfile"
  [strategy-runner]="services/strategy-runner/Dockerfile"
  [api-gateway]="services/api-gateway/Dockerfile"
  # Python services (some use repo root context, some use service dir)
  [feature-builder]="services/feature-builder/Dockerfile"
  [dataset-builder]="services/dataset-builder/Dockerfile"
  [rl-train]="services/rl-train/Dockerfile"
  [temporal-worker]="services/temporal-worker/Dockerfile"
  [kaggle-orchestrator]="services/kaggle-orchestrator/Dockerfile"
  [dashboard]="services/dashboard/Dockerfile"
  [web-ui]="services/web-ui/Dockerfile"
)

# Services that use their own directory as build context (not repo root)
SELF_CONTEXT_SERVICES="backtest rl-infer temporal-worker kaggle-orchestrator dashboard web-ui"

# Parse args
TARGETS=()
for arg in "$@"; do
  if [ "$arg" = "--build-only" ]; then
    BUILD_ONLY=true
  else
    TARGETS+=("$arg")
  fi
done

# Default to all services
if [ ${#TARGETS[@]} -eq 0 ]; then
  TARGETS=("${!SERVICES[@]}")
  # Add backtest and rl-infer which have different context
  TARGETS+=("backtest" "rl-infer")
fi

# Login to GHCR
if [ "$BUILD_ONLY" = false ]; then
  if [ -z "${GITHUB_TOKEN:-}" ]; then
    echo "Error: GITHUB_TOKEN env var required for push (write:packages scope)"
    exit 1
  fi
  echo "$GITHUB_TOKEN" | docker login ghcr.io -u ntjohns1 --password-stdin
fi

echo "=== Building ${#TARGETS[@]} service(s) ==="
echo "Registry: $REGISTRY"
echo "Git SHA:  $GIT_SHA"
echo ""

FAILED=()
for svc in "${TARGETS[@]}"; do
  echo "──── Building: $svc ────"

  # Determine build context and dockerfile
  if echo "$SELF_CONTEXT_SERVICES" | grep -qw "$svc"; then
    CONTEXT="$REPO_ROOT/services/$svc"
    DOCKERFILE="$CONTEXT/Dockerfile"
  else
    CONTEXT="$REPO_ROOT"
    DOCKERFILE="$REPO_ROOT/services/$svc/Dockerfile"
  fi

  if [ ! -f "$DOCKERFILE" ]; then
    echo "[warn] No Dockerfile found at $DOCKERFILE — skipping"
    continue
  fi

  IMAGE="$REGISTRY/$svc"

  if docker build -t "$IMAGE:latest" -t "$IMAGE:$GIT_SHA" -f "$DOCKERFILE" "$CONTEXT"; then
    echo "[built] $IMAGE:latest"

    if [ "$BUILD_ONLY" = false ]; then
      docker push "$IMAGE:latest" && docker push "$IMAGE:$GIT_SHA"
      echo "[pushed] $IMAGE:latest + $IMAGE:$GIT_SHA"
    fi
  else
    echo "[FAIL] $svc build failed"
    FAILED+=("$svc")
  fi
  echo ""
done

if [ ${#FAILED[@]} -gt 0 ]; then
  echo "=== FAILED builds: ${FAILED[*]} ==="
  exit 1
fi

echo "=== All builds complete ==="
