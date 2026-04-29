#!/usr/bin/env bash
# swarm-init.sh — Bootstrap Docker Swarm on server_1 (manager node)
#
# Run this ONCE on server_1 (192.168.10.104):
#   chmod +x infra/scripts/swarm-init.sh
#   ./infra/scripts/swarm-init.sh
set -euo pipefail

MANAGER_IP="192.168.10.104"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Docker Swarm Init ==="
echo "Manager node: $MANAGER_IP"
echo ""

# ── 1. Init Swarm ────────────────────────────────────────────────────────
if docker info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null | grep -q "active"; then
  echo "[skip] Swarm already active on this node"
else
  echo "[init] Initializing Swarm..."
  docker swarm init --advertise-addr "$MANAGER_IP"
fi

# ── 2. Label this node ──────────────────────────────────────────────────
NODE_ID=$(docker node ls --format '{{.ID}}' --filter "role=manager" | head -1)
echo "[label] Labeling manager node as role=data"
docker node update --label-add role=data "$NODE_ID"

# ── 3. Generate production secrets ──────────────────────────────────────
echo ""
if [ -f "$INFRA_DIR/.env.production" ]; then
  echo "[skip] .env.production already exists"
  echo "  To regenerate: rm $INFRA_DIR/.env.production && rerun this script"
else
  echo "=== Generating Production Secrets ==="
  "$SCRIPT_DIR/generate-secrets.sh"
fi

# ── 4. Change password on running postgres ──────────────────────────────
echo ""
echo "=== Database Password Migration ==="

# Source the new password
set -a
# shellcheck disable=SC1091
source "$INFRA_DIR/.env.production"
set +a

POSTGRES_CONTAINER=$(docker ps -q -f name=postgres 2>/dev/null || true)
if [ -n "$POSTGRES_CONTAINER" ]; then
  echo "Found running postgres container: $POSTGRES_CONTAINER"
  read -rp "Change postgres rl_user password to the new generated password? [y/N] " confirm
  if [ "$confirm" = "y" ]; then
    docker exec "$POSTGRES_CONTAINER" psql -U rl_user -d alpaca_rl \
      -c "ALTER USER rl_user WITH PASSWORD '${DB_PASSWORD}';"
    echo "[done] Password changed on running postgres"
    echo ""
    echo "Verify with:"
    echo "  docker exec $POSTGRES_CONTAINER psql 'postgresql://rl_user:${DB_PASSWORD}@localhost:5432/alpaca_rl' -c 'SELECT 1;'"
  else
    echo "[skip] Password not changed. You must change it manually before deploying:"
    echo "  docker exec -it $POSTGRES_CONTAINER psql -U rl_user -d alpaca_rl"
    echo "  ALTER USER rl_user WITH PASSWORD '<password from .env.production>';"
  fi
else
  echo "[info] No running postgres container found."
  echo "  The new password will be used when postgres starts fresh."
  echo "  If you have an existing postgres with data, start it and rerun this script."
fi

# ── 5. Open firewall ports ──────────────────────────────────────────────
echo ""
echo "=== Firewall ==="
if command -v ufw &>/dev/null; then
  sudo ufw allow 2377/tcp comment "Swarm management" 2>/dev/null || true
  sudo ufw allow 7946/tcp comment "Swarm cluster comm" 2>/dev/null || true
  sudo ufw allow 7946/udp comment "Swarm cluster comm" 2>/dev/null || true
  sudo ufw allow 4789/udp comment "Swarm overlay VXLAN" 2>/dev/null || true
  echo "[done] UFW rules added"
else
  echo "[info] UFW not found — ensure these ports are open:"
  echo "  TCP 2377 (swarm management)"
  echo "  TCP+UDP 7946 (cluster communication)"
  echo "  UDP 4789 (overlay VXLAN)"
fi

# ── 6. Print join token ─────────────────────────────────────────────────
echo ""
echo "=== Worker Join Token ==="
echo "Run this command on each worker node (server_7 and server_6):"
echo ""
docker swarm join-token worker 2>/dev/null | grep "docker swarm join"
echo ""
echo "After workers join, label them from this manager node:"
echo ""
echo "  # Find node IDs:"
echo "  docker node ls"
echo ""
echo "  # Label server_7 (192.168.10.113):"
echo "  docker node update --label-add role=compute <server_7_node_id>"
echo ""
echo "  # Label server_6 (192.168.10.105):"
echo "  docker node update --label-add role=trading <server_6_node_id>"
echo ""
echo "Then run: ./infra/scripts/deploy.sh"
