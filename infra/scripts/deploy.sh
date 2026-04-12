#!/usr/bin/env bash
# deploy.sh — Build, push, and deploy the Swarm stack
#
# Usage:
#   ./deploy.sh                # Full: build + push + deploy
#   ./deploy.sh --deploy-only  # Skip build, just (re)deploy stack
#   ./deploy.sh --build-only   # Build + push, don't deploy
#
# Run from the manager node (server_1).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(dirname "$SCRIPT_DIR")"
STACK_NAME="alpaca-rl"
STACK_FILE="$INFRA_DIR/docker-stack.yml"

BUILD_ONLY=false
DEPLOY_ONLY=false

for arg in "$@"; do
  case "$arg" in
    --build-only)  BUILD_ONLY=true ;;
    --deploy-only) DEPLOY_ONLY=true ;;
  esac
done

# ── Source production env ───────────────────────────────────────────────
ENV_PRODUCTION="$INFRA_DIR/.env.production"
if [ -f "$ENV_PRODUCTION" ]; then
  echo "=== Loading .env.production ==="
  set -a
  # shellcheck disable=SC1090
  source "$ENV_PRODUCTION"
  set +a
  echo "Loaded $(grep -c '=' "$ENV_PRODUCTION" | head -1) variables from .env.production"
else
  echo "ERROR: $ENV_PRODUCTION not found."
  echo "Run: ./infra/scripts/generate-secrets.sh"
  exit 1
fi

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

# ── Pre-flight checks ──────────────────────────────────────────────────
echo ""
echo "=== Pre-flight Checks ==="

if ! docker info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null | grep -q "active"; then
  echo "Error: This node is not part of a Swarm. Run swarm-init.sh first."
  exit 1
fi

NODE_COUNT=$(docker node ls --format '{{.ID}}' 2>/dev/null | wc -l)
echo "Swarm nodes: $NODE_COUNT"

# Check node labels
echo ""
echo "Node labels:"
for node_id in $(docker node ls --format '{{.ID}}'); do
  hostname=$(docker node inspect "$node_id" --format '{{.Description.Hostname}}')
  role=$(docker node inspect "$node_id" --format '{{index .Spec.Labels "role"}}' 2>/dev/null || echo "<none>")
  echo "  $hostname: role=$role"
done

ROLES_OK=true
for required_role in data compute trading; do
  if ! docker node ls --format '{{.ID}}' | while read nid; do
    docker node inspect "$nid" --format '{{index .Spec.Labels "role"}}' 2>/dev/null
  done | grep -q "$required_role"; then
    echo "WARNING: No node labeled role=$required_role"
    ROLES_OK=false
  fi
done

if [ "$ROLES_OK" = false ]; then
  echo ""
  read -rp "Missing node labels. Continue anyway? [y/N] " confirm
  [ "$confirm" = "y" ] || exit 1
fi

# ── Build + Push ────────────────────────────────────────────────────────
if [ "$DEPLOY_ONLY" = false ]; then
  echo ""
  echo "=== Build & Push ==="
  "$SCRIPT_DIR/build-push.sh"
fi

if [ "$BUILD_ONLY" = true ]; then
  echo "=== Build complete (--build-only). Skipping deploy. ==="
  exit 0
fi

# ── Deploy ──────────────────────────────────────────────────────────────
echo ""
echo "=== Deploying Stack: $STACK_NAME ==="
docker stack deploy -c "$STACK_FILE" "$STACK_NAME" --with-registry-auth

echo ""
echo "=== Waiting for services to start... ==="
sleep 5

echo ""
echo "=== Service Status ==="
docker stack services "$STACK_NAME"

echo ""
echo "=== Deployment complete ==="
echo ""
echo "Useful commands:"
echo "  docker stack services $STACK_NAME           # Service overview"
echo "  docker service ps ${STACK_NAME}_web-ui      # Where is web-ui running?"
echo "  docker service logs ${STACK_NAME}_postgres   # View postgres logs"
echo "  docker stack rm $STACK_NAME                  # Tear down (volumes preserved)"
