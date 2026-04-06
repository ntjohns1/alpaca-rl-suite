#!/usr/bin/env bash
# =============================================================================
# setup-vps-runner.sh
#
# Bootstrap a self-hosted GitHub Actions runner for the alpaca-rl-suite repo
# on a VPS running Ubuntu/Debian.
#
# Usage:
#   sudo bash infra/scripts/setup-vps-runner.sh \
#     --token <REGISTRATION_TOKEN> \
#     [--repo  https://github.com/ntjohns1/alpaca-rl-suite] \
#     [--runner-version 2.319.1] \
#     [--runner-name my-vps]
#
# Re-running is safe: idempotency guards skip already-completed steps.
# =============================================================================
set -euo pipefail
IFS=$'\n\t'

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'
NC='\033[0m'
log()  { echo -e "${GREEN}[RUNNER-SETUP]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── Defaults ──────────────────────────────────────────────────────────────────
REGISTRATION_TOKEN=""
REPO_URL="https://github.com/ntjohns1/alpaca-rl-suite"
RUNNER_VERSION=""           # empty → fetch latest from GitHub API
RUNNER_USER="github-runner"
RUNNER_HOME="/opt/github-runner"
RUNNER_LABELS="self-hosted,linux,vps"
RUNNER_NAME="${RUNNER_NAME:-$(hostname -s)-alpaca-rl}"
# NOTE: the actual systemd service name is set by svc.sh (not predictable in
# advance) — it is detected after install as actions.runner.<org>-<repo>.<name>

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --token)           REGISTRATION_TOKEN="$2"; shift 2 ;;
    --repo)            REPO_URL="$2";            shift 2 ;;
    --runner-version)  RUNNER_VERSION="$2";      shift 2 ;;
    --runner-name)     RUNNER_NAME="$2";         shift 2 ;;
    *) err "Unknown argument: $1. See infra/scripts/README.md for usage." ;;
  esac
done

[[ -n "$REGISTRATION_TOKEN" ]] || err "--token is required. See infra/scripts/README.md."
[[ "$(id -u)" -eq 0 ]]         || err "This script must be run as root (sudo)."

# ── Step 1: System packages ───────────────────────────────────────────────────
log "Step 1/7 — Installing system packages..."

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq

# Core utilities
apt-get install -y -qq git curl jq ca-certificates gnupg lsb-release

# Python 3.11
# actions/setup-python@v5 on a self-hosted runner checks PATH for a matching
# python before attempting a download.  Pre-installing python3.11 means the
# action satisfies python-version: '3.11' immediately and cache: pip works.
if ! command -v python3.11 &>/dev/null; then
  log "  Installing Python 3.11 via deadsnakes PPA..."
  add-apt-repository -y ppa:deadsnakes/ppa
  apt-get update -qq
  apt-get install -y -qq python3.11 python3.11-venv python3.11-dev python3-pip
else
  log "  python3.11 already installed: $(python3.11 --version)"
fi

# Ensure pip works for 3.11
if ! python3.11 -m pip --version &>/dev/null 2>&1; then
  curl -sSf https://bootstrap.pypa.io/get-pip.py | python3.11
fi

# ── Step 2: Docker Engine + Compose v2 plugin ────────────────────────────────
log "Step 2/7 — Installing Docker Engine + Compose v2 plugin..."

if ! command -v docker &>/dev/null; then
  log "  Installing Docker via get.docker.com..."
  curl -fsSL https://get.docker.com | sh
else
  log "  Docker already installed: $(docker --version)"
fi

# Compose v2 plugin (docker compose, no hyphen).  The integration workflow
# uses `docker compose` exclusively; v1 docker-compose is intentionally not
# installed to prevent ambiguity.
if ! docker compose version &>/dev/null 2>&1; then
  log "  Installing docker-compose-plugin..."
  apt-get install -y -qq docker-compose-plugin
else
  log "  docker compose already available: $(docker compose version)"
fi

systemctl enable --now docker
log "  Docker daemon enabled and started."

# ── Step 3: github-runner system user ────────────────────────────────────────
log "Step 3/7 — Ensuring '${RUNNER_USER}' system user exists..."

if id "${RUNNER_USER}" &>/dev/null; then
  log "  User '${RUNNER_USER}' already exists."
else
  useradd \
    --system \
    --create-home \
    --home-dir "${RUNNER_HOME}" \
    --shell /bin/bash \
    --comment "GitHub Actions runner" \
    "${RUNNER_USER}"
  log "  Created user '${RUNNER_USER}'."
fi

# Docker group membership is required: the workflow runs `docker compose` steps
# without sudo, so the runner process must be able to reach the Docker socket.
if groups "${RUNNER_USER}" | grep -q '\bdocker\b'; then
  log "  '${RUNNER_USER}' already in docker group."
else
  usermod -aG docker "${RUNNER_USER}"
  log "  Added '${RUNNER_USER}' to docker group."
fi

# ── Step 4: Runner home directory ─────────────────────────────────────────────
log "Step 4/7 — Preparing runner installation directory (${RUNNER_HOME})..."

mkdir -p "${RUNNER_HOME}"
chown "${RUNNER_USER}:${RUNNER_USER}" "${RUNNER_HOME}"

# ── Step 5: Download runner binary ────────────────────────────────────────────
log "Step 5/7 — Downloading GitHub Actions runner binary..."

ARCH="$(uname -m)"
case "${ARCH}" in
  x86_64)  RUNNER_ARCH="x64"   ;;
  aarch64) RUNNER_ARCH="arm64" ;;
  armv7l)  RUNNER_ARCH="arm"   ;;
  *) err "Unsupported architecture: ${ARCH}" ;;
esac

# Fetch latest version from GitHub API if not specified.
if [[ -z "${RUNNER_VERSION}" ]]; then
  log "  Fetching latest runner version from GitHub API..."
  RUNNER_VERSION=$(
    curl -fsSL "https://api.github.com/repos/actions/runner/releases/latest" \
      | jq -r '.tag_name' \
      | sed 's/^v//'
  )
  log "  Latest runner version: ${RUNNER_VERSION}"
fi

RUNNER_TARBALL="actions-runner-linux-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz"
RUNNER_URL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${RUNNER_TARBALL}"
RUNNER_DEST="${RUNNER_HOME}/${RUNNER_TARBALL}"

# Idempotency: skip download if the correct version is already extracted.
NEEDS_DOWNLOAD=true
if [[ -x "${RUNNER_HOME}/run.sh" ]]; then
  # run.sh --version may print to stderr on some releases; capture both streams
  INSTALLED_VERSION=$("${RUNNER_HOME}/run.sh" --version 2>&1 || true)
  if [[ "${INSTALLED_VERSION}" == "${RUNNER_VERSION}" ]]; then
    log "  Runner v${RUNNER_VERSION} already extracted — skipping download."
    NEEDS_DOWNLOAD=false
  else
    warn "  Installed runner version '${INSTALLED_VERSION}' differs from '${RUNNER_VERSION}' — re-downloading."
    rm -f "${RUNNER_DEST}"
  fi
fi

if [[ "${NEEDS_DOWNLOAD}" == true ]]; then
  log "  Downloading ${RUNNER_URL} ..."
  curl -fsSL -o "${RUNNER_DEST}" "${RUNNER_URL}"
  log "  Extracting tarball..."
  tar -xzf "${RUNNER_DEST}" -C "${RUNNER_HOME}"
  rm -f "${RUNNER_DEST}"
  chown -R "${RUNNER_USER}:${RUNNER_USER}" "${RUNNER_HOME}"
  log "  Runner binary extracted."
fi

# ── Step 6: Register the runner ───────────────────────────────────────────────
log "Step 6/7 — Registering runner with GitHub..."

# config.sh creates .runner on success.  If it exists, registration already
# happened (or was done manually) — skip to avoid consuming the one-hour token.
if [[ -f "${RUNNER_HOME}/.runner" ]]; then
  warn "  Runner already configured (.runner file present)."
  warn "  To re-register: remove ${RUNNER_HOME}/.runner and provide a fresh token."
else
  sudo -u "${RUNNER_USER}" \
    "${RUNNER_HOME}/config.sh" \
      --unattended \
      --url    "${REPO_URL}" \
      --token  "${REGISTRATION_TOKEN}" \
      --name   "${RUNNER_NAME}" \
      --labels "${RUNNER_LABELS}" \
      --work   "_work"
  log "  Runner registered: name='${RUNNER_NAME}' labels=[${RUNNER_LABELS}]"
fi

# ── Step 7: Systemd service ───────────────────────────────────────────────────
log "Step 7/7 — Installing runner as systemd service..."

# svc.sh (shipped inside the runner tarball) generates the correct unit file
# with User=, WorkingDirectory=, and Restart=always.  The service name is
# derived from the GitHub org/repo and runner name — e.g.:
#   actions.runner.ntjohns1-alpaca-rl-suite.<runner-name>.service
# We cannot predict it in advance, so we detect it after install.

# Only call install if no actions.runner unit file exists yet.
if compgen -G "/etc/systemd/system/actions.runner.*.service" > /dev/null 2>&1; then
  log "  Systemd unit already exists — skipping install."
else
  (cd "${RUNNER_HOME}" && ./svc.sh install "${RUNNER_USER}")
  log "  Systemd unit installed."
fi

# Detect the actual service name created by svc.sh.
ACTUAL_SERVICE=$(
  basename "$(compgen -G "/etc/systemd/system/actions.runner.*.service" | head -1)" .service
)
[[ -n "${ACTUAL_SERVICE}" ]] \
  || err "Could not find actions.runner.*.service unit. Check: ls /etc/systemd/system/actions.runner.*"
log "  Detected service name: ${ACTUAL_SERVICE}"

systemctl daemon-reload
systemctl enable "${ACTUAL_SERVICE}"
systemctl restart "${ACTUAL_SERVICE}"
sleep 2

if systemctl is-active --quiet "${ACTUAL_SERVICE}"; then
  log "  Service '${ACTUAL_SERVICE}' is active."
else
  err "Service '${ACTUAL_SERVICE}' failed to start. Run: journalctl -u ${ACTUAL_SERVICE} -n 50"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║            Runner bootstrap complete                     ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  Runner name:    ${RUNNER_NAME}"
echo "  Labels:         ${RUNNER_LABELS}"
echo "  Install dir:    ${RUNNER_HOME}"
echo "  Service:        ${ACTUAL_SERVICE}"
echo "  Runner version: ${RUNNER_VERSION}"
echo ""
echo "Next steps:"
echo "  1. Confirm the runner shows 'Idle' in GitHub:"
echo "     https://github.com/ntjohns1/alpaca-rl-suite/settings/actions/runners"
echo ""
echo "  2. Verify Docker access as the runner user:"
echo "     sudo -u ${RUNNER_USER} docker info"
echo ""
echo "  3. Trigger a test workflow run:"
echo "     gh workflow run integration.yml --repo ntjohns1/alpaca-rl-suite"
echo "     gh run watch --repo ntjohns1/alpaca-rl-suite"
echo ""
echo "  4. Monitor service logs:"
echo "     journalctl -u ${ACTUAL_SERVICE} -f"
echo ""
