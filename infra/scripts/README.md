# infra/scripts — CI Runner Bootstrap

## setup-vps-runner.sh

Bootstraps a self-hosted GitHub Actions runner on a Debian/Ubuntu VPS.
The runner registers against `https://github.com/ntjohns1/alpaca-rl-suite`
with labels `self-hosted,linux,vps`, which is what `integration.yml` targets.

### What the script installs

| Component | Notes |
|---|---|
| Git | Required by `actions/checkout@v4` |
| Docker Engine | Installed via `get.docker.com` |
| Docker Compose v2 plugin | `docker compose` (no hyphen); v1 is NOT installed |
| Python 3.11 | Via deadsnakes PPA; satisfies `actions/setup-python@v5` from PATH |
| `github-runner` system user | Unprivileged; home `/opt/github-runner`; member of `docker` group |
| GitHub Actions runner binary | Fetched from GitHub API (latest) unless `--runner-version` is set |
| systemd service `github-runner-alpaca-rl` | Starts on boot; restarts automatically on failure |

The script is **idempotent** — re-running it after a successful bootstrap is safe.

---

### Prerequisites

- VPS running Ubuntu 22.04+ or Debian 12+ (x86_64 or arm64)
- Root or sudo access
- Outbound HTTPS to `github.com` and `api.github.com`
- At least 20 GB free disk (Docker images + TimescaleDB volume)

---

### Step 1 — Get a registration token

Registration tokens expire after **1 hour**.

**Via GitHub CLI (recommended):**
```bash
gh api \
  --method POST \
  -H "Accept: application/vnd.github+json" \
  /repos/ntjohns1/alpaca-rl-suite/actions/runners/registration-token \
  --jq '.token'
```

**Via browser:**
GitHub repo → **Settings → Actions → Runners → New self-hosted runner** → copy the token shown in the `--token` line of the configure step.

---

### Step 2 — Run the script on the VPS

Copy the script (or clone the repo) to the VPS, then:

```bash
# Required
sudo bash infra/scripts/setup-vps-runner.sh --token <TOKEN_FROM_STEP_1>

# Optional flags
#   --repo            https://github.com/ntjohns1/alpaca-rl-suite  (default)
#   --runner-version  2.319.1   (default: fetched from GitHub API)
#   --runner-name     cicd-vps  (default: hostname-alpaca-rl)
```

---

### Step 3 — Verify

```bash
# Service health
sudo systemctl status github-runner-alpaca-rl

# Runner visible in GitHub (status should be "Idle")
gh api /repos/ntjohns1/alpaca-rl-suite/actions/runners \
  --jq '.runners[] | {name, status, labels: [.labels[].name]}'

# Docker access works as the runner user (no sudo)
sudo -u github-runner docker info
sudo -u github-runner docker run --rm hello-world

# Confirm test ports are free before triggering a run
for port in 15432 18002 18003 18011 19000 19001; do
  ss -tlnp | grep ":${port} " && echo "PORT $port IN USE — check for conflicts" || echo "port $port free"
done

# Trigger the integration workflow manually
gh workflow run integration.yml --repo ntjohns1/alpaca-rl-suite
gh run watch --repo ntjohns1/alpaca-rl-suite
```

---

### Removing / re-registering the runner

```bash
# Stop and remove the service
cd /opt/github-runner
sudo ./svc.sh stop
sudo ./svc.sh uninstall

# Remove the runner from GitHub and delete local config
REMOVAL_TOKEN=$(gh api --method POST \
  /repos/ntjohns1/alpaca-rl-suite/actions/runners/remove-token --jq '.token')
sudo -u github-runner /opt/github-runner/config.sh remove --token "${REMOVAL_TOKEN}"

# Re-register with a fresh token
FRESH_TOKEN=$(gh api --method POST \
  /repos/ntjohns1/alpaca-rl-suite/actions/runners/registration-token --jq '.token')
sudo bash infra/scripts/setup-vps-runner.sh --token "${FRESH_TOKEN}"
```

---

### Integration test stack port assignments

These ports are bound only during a test run and released by the `docker compose down -v` teardown step.

| Service | Test host port | Production host port |
|---|---|---|
| PostgreSQL (TimescaleDB) | 15432 | 5432 |
| MinIO API | 19000 | 9000 |
| MinIO console | 19001 | 9001 |
| feature-builder | 18002 | 8002 |
| dataset-builder | 18003 | 8003 |
| kaggle-orchestrator | 18011 | 8011 |

Test ports are offset by +10000 from production ports, so both stacks can run on the same host without conflicts.

---

### Troubleshooting

**Runner shows "Offline" after bootstrap:**
```bash
journalctl -u github-runner-alpaca-rl -n 50
```
Common causes: network issue reaching `github.com`, or the registration token expired mid-run. Get a fresh token and re-run the script (it skips already-completed steps).

**`docker: permission denied` during a workflow run:**
The runner user may not have picked up the docker group yet (group membership requires a new session). Restart the service:
```bash
sudo systemctl restart github-runner-alpaca-rl
```

**Disk fills up over time:**
The integration workflow includes a `docker builder prune` step after each run. If space is still tight:
```bash
docker system prune -af --volumes
```
