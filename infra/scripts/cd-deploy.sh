#!/usr/bin/env bash
# cd-deploy.sh — Non-interactive deploy script for CI/CD pipeline
#
# Executed on server_1 (Swarm manager) via SSH from the GitHub Actions runner.
# Expects to be piped via: ssh user@host "GHCR_TOKEN=... bash -s" < cd-deploy.sh
#
# Required env vars:
#   GHCR_TOKEN   — GitHub token with read:packages scope (for docker login)
#   GITHUB_SHA   — Git commit SHA being deployed (for logging)
#
# Reads .env.production from the repo checkout on server_1.
set -euo pipefail

REPO_DIR="${DEPLOY_REPO_DIR:-/opt/alpaca-rl-suite}"
STACK_NAME="alpaca-rl"
STACK_FILE="$REPO_DIR/infra/docker-stack.yml"
ENV_PRODUCTION="$REPO_DIR/infra/.env.production"
CONVERGE_TIMEOUT=120  # seconds

echo "=== CD Deploy: ${GITHUB_SHA:-unknown} ==="
echo "Repo dir:   $REPO_DIR"
echo "Stack file: $STACK_FILE"
echo ""

# ── Pull latest code ───────────────────────────────────────────────────
echo "=== Pulling latest code ==="
cd "$REPO_DIR"
git fetch origin master
git reset --hard origin/master
echo "At commit: $(git rev-parse --short HEAD)"
echo ""

# ── Source production env ──────────────────────────────────────────────
if [ ! -f "$ENV_PRODUCTION" ]; then
  echo "ERROR: $ENV_PRODUCTION not found on server_1."
  exit 1
fi

echo "=== Loading .env.production ==="
set -a
# shellcheck disable=SC1090
source "$ENV_PRODUCTION"
set +a
echo "Loaded $(grep -c '=' "$ENV_PRODUCTION" | head -1) variables"
echo ""

# ── Validate required vars ─────────────────────────────────────────────
MISSING=()
for var in DB_PASSWORD S3_ACCESS_KEY S3_SECRET_KEY JWT_SECRET ALPACA_API_KEY ALPACA_API_SECRET GF_ADMIN_PASSWORD; do
  if [ -z "${!var:-}" ] || [ "${!var}" = "CHANGE_ME" ]; then
    MISSING+=("$var")
  fi
done
if [ ${#MISSING[@]} -gt 0 ]; then
  echo "ERROR: Missing or placeholder values in .env.production:"
  printf '  %s\n' "${MISSING[@]}"
  exit 1
fi

# ── Login to GHCR ─────────────────────────────────────────────────────
if [ -z "${GHCR_TOKEN:-}" ]; then
  echo "ERROR: GHCR_TOKEN env var is required"
  exit 1
fi

echo "=== Logging in to GHCR ==="
echo "$GHCR_TOKEN" | docker login ghcr.io -u ntjohns1 --password-stdin
echo ""

# ── Pre-flight checks ─────────────────────────────────────────────────
echo "=== Pre-flight Checks ==="

if ! docker info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null | grep -q "active"; then
  echo "ERROR: This node is not part of a Swarm."
  exit 1
fi

NODE_COUNT=$(docker node ls --format '{{.ID}}' 2>/dev/null | wc -l)
echo "Swarm nodes: $NODE_COUNT"

echo ""
echo "Node labels:"
for node_id in $(docker node ls --format '{{.ID}}'); do
  hostname=$(docker node inspect "$node_id" --format '{{.Description.Hostname}}')
  role=$(docker node inspect "$node_id" --format '{{index .Spec.Labels "role"}}' 2>/dev/null || echo "<none>")
  echo "  $hostname: role=$role"
done
echo ""

# ── Record pre-deploy state ───────────────────────────────────────────
echo "=== Pre-deploy service state ==="
docker stack services "$STACK_NAME" --format '{{.Name}} {{.Image}} {{.Replicas}}' 2>/dev/null || echo "(no existing stack)"
echo ""

# ── Deploy ─────────────────────────────────────────────────────────────
echo "=== Deploying Stack: $STACK_NAME ==="
docker stack deploy -c "$STACK_FILE" "$STACK_NAME" --with-registry-auth

# ── Wait for convergence ──────────────────────────────────────────────
echo ""
echo "=== Waiting for services to converge (timeout: ${CONVERGE_TIMEOUT}s) ==="

ELAPSED=0
INTERVAL=10

while [ $ELAPSED -lt $CONVERGE_TIMEOUT ]; do
  sleep $INTERVAL
  ELAPSED=$((ELAPSED + INTERVAL))

  NOT_READY=()
  for svc in $(docker stack services "$STACK_NAME" --format '{{.Name}}'); do
    REPLICAS_INFO=$(docker service ls --filter "name=$svc" --format '{{.Replicas}}')
    RUNNING=$(echo "$REPLICAS_INFO" | cut -d/ -f1)
    DESIRED=$(echo "$REPLICAS_INFO" | cut -d/ -f2)
    if [ "$RUNNING" != "$DESIRED" ]; then
      NOT_READY+=("$svc ($RUNNING/$DESIRED)")
    fi
  done

  if [ ${#NOT_READY[@]} -eq 0 ]; then
    echo "All services converged after ${ELAPSED}s"
    break
  fi

  echo "  [${ELAPSED}s] Waiting on: ${NOT_READY[*]}"
done

# ── Final check ────────────────────────────────────────────────────────
FAILED=()
for svc in $(docker stack services "$STACK_NAME" --format '{{.Name}}'); do
  REPLICAS_INFO=$(docker service ls --filter "name=$svc" --format '{{.Replicas}}')
  RUNNING=$(echo "$REPLICAS_INFO" | cut -d/ -f1)
  DESIRED=$(echo "$REPLICAS_INFO" | cut -d/ -f2)
  if [ "$RUNNING" != "$DESIRED" ]; then
    FAILED+=("$svc")
  fi
done

echo ""
echo "=== Post-deploy service status ==="
docker stack services "$STACK_NAME"

if [ ${#FAILED[@]} -gt 0 ]; then
  echo ""
  echo "ERROR: Services failed to converge: ${FAILED[*]}"
  echo ""
  echo "=== Attempting rollback of failed services ==="
  for svc in "${FAILED[@]}"; do
    echo "Rolling back $svc..."
    docker service rollback "$svc" || true
  done
  exit 1
fi

echo ""
echo "=== Deployment successful ==="
echo "Commit: ${GITHUB_SHA:-$(git rev-parse --short HEAD)}"
echo "Stack:  $STACK_NAME"
