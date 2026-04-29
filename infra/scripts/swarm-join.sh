#!/usr/bin/env bash
# swarm-join.sh — Join a worker node to the Swarm and log into GHCR
#
# Usage (run on each worker node):
#   ./swarm-join.sh <join-token> <role>
#
# Example:
#   ./swarm-join.sh SWMTKN-1-xxx compute    # server_7
#   ./swarm-join.sh SWMTKN-1-xxx trading    # server_6
set -euo pipefail

MANAGER_IP="192.168.10.104"

if [ $# -lt 2 ]; then
  echo "Usage: $0 <swarm-join-token> <role>"
  echo "  role: compute (server_7) or trading (server_6)"
  exit 1
fi

JOIN_TOKEN="$1"
ROLE="$2"

echo "=== Swarm Worker Join ==="
echo "Role: $ROLE"
echo "Manager: $MANAGER_IP"
echo ""

# ── 1. Join the Swarm ───────────────────────────────────────────────────
if docker info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null | grep -q "active"; then
  echo "[skip] Already part of a Swarm"
else
  echo "[join] Joining Swarm..."
  docker swarm join --token "$JOIN_TOKEN" "${MANAGER_IP}:2377"
fi

# ── 2. Log into GHCR ───────────────────────────────────────────────────
echo ""
echo "[ghcr] Logging into GitHub Container Registry..."
echo "Enter a GitHub PAT with read:packages scope:"
read -rsp "Token: " GITHUB_TOKEN
echo ""
echo "$GITHUB_TOKEN" | docker login ghcr.io -u ntjohns1 --password-stdin
echo "[ghcr] Login successful"

# ── 3. Open firewall ports ──────────────────────────────────────────────
echo ""
echo "[firewall] Ensuring Swarm ports are open..."
if command -v ufw &>/dev/null; then
  sudo ufw allow 2377/tcp comment "Swarm management" 2>/dev/null || true
  sudo ufw allow 7946/tcp comment "Swarm cluster comm" 2>/dev/null || true
  sudo ufw allow 7946/udp comment "Swarm cluster comm" 2>/dev/null || true
  sudo ufw allow 4789/udp comment "Swarm overlay VXLAN" 2>/dev/null || true
  echo "[firewall] UFW rules added"
else
  echo "[firewall] UFW not found — ensure these ports are open:"
  echo "  TCP 2377 (swarm management)"
  echo "  TCP+UDP 7946 (cluster communication)"
  echo "  UDP 4789 (overlay VXLAN)"
fi

echo ""
echo "=== Done ==="
echo "Now go to the manager node (server_1) and label this worker:"
echo ""
echo "  docker node ls    # find this node's ID"
echo "  docker node update --label-add role=${ROLE} <node_id>"
