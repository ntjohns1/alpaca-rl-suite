# Testing & CI/CD: Pipeline Correctness First

Implement functional tests proving the SHARADAR 20-feature pipeline works end-to-end (feature-builder → dataset-builder → kaggle-orchestrator → notebook), set up a hybrid CI/CD pipeline with GitHub Actions for fast checks and a separate lightweight VPS for Docker Compose integration tests.

## Current State

- **Good unit coverage**: dataset-builder (283 lines), kaggle-orchestrator (405 lines), rl-train/trading_env (279 lines)
- **Zero tests**: feature-builder, web-ui proxy, frontend, api-gateway, portfolio, rl-infer, temporal-worker
- **CI**: Basic `ci.yml` — Node lint/typecheck/test + Python lint/test per service + docker-compose validate
- **Highest risk**: The 10→20 feature column expansion (SHARADAR enrichment) touches feature-builder, dataset-builder, kaggle-orchestrator, trading_env, and the notebook — no integration tests prove columns flow correctly across boundaries

## Phase 1 — Feature-Builder Unit Tests (local, no DB)

Create `services/feature-builder/tests/test_feature_builder.py`:

| Test | What it proves |
|------|---------------|
| `compute_features` produces all 20 columns from OHLCV+SHARADAR input | Core logic works |
| `compute_features` drops rows with NaN in TECHNICAL_COLS, preserves NaN SHARADAR | Correct null handling |
| `merge_sharadar_features` with empty SHARADAR tables fills NaN | Graceful degradation |
| `build_state_vector` returns exactly 20 floats, NaN→0 | State vector contract |
| `_safe_float` handles None/NaN/inf/normal | Edge case coverage |
| Winsorization clips PE/PB/PS/EVEBITDA to [-1000, 1000] | Outlier handling |
| API endpoints (`/features/build`, `/features/latest`, `/features/availability`) via TestClient with mocked DB | Contract tests |

All mocked — same pattern as existing dataset-builder tests.

## Phase 2 — Cross-Service Column Alignment Tests

Create `tests/functional/test_pipeline_column_alignment.py` — **runs without Docker**, uses mocked DB calls to verify data shapes flow correctly across service boundaries:

| Test | What it proves |
|------|---------------|
| feature-builder `compute_features` output columns == `ALL_FEATURE_COLS` | Source of truth match |
| dataset-builder `fetch_features` SQL selects all 20 feature cols + OHLCV | No missing columns |
| kaggle-orchestrator `export_training_dataset` SQL selects all 20 feature cols + close | Export shape correct |
| Notebook `DataSource.FEATURE_COLS` == `ALL_FEATURE_COLS` | Notebook alignment |
| trading_env `DataSource._active_cols` (precomputed) == `ALL_FEATURE_COLS` | Env alignment |
| End-to-end: mock feature rows → dataset-builder build → verify parquet has all 20 cols | Full shape test |
| End-to-end: mock feature rows → kaggle export → load as notebook DataSource → obs shape == (20,) | Training pipeline shape |

These are the **highest-value tests** — they catch the exact class of bug where one service adds/removes a column but downstream consumers are stale.

## Phase 3 — Docker Compose Integration Tests (VPS)

Create `tests/integration/` with a `docker-compose.test.yml` (slim: postgres + minio + feature-builder + dataset-builder + kaggle-orchestrator only):

| Test | What it proves |
|------|---------------|
| POST `/features/build` for a seeded symbol → rows appear in DB with all 20 cols | Feature build works against real DB |
| POST `/datasets/build` with pre-seeded feature rows → parquet in MinIO has correct schema | Dataset build works end-to-end |
| POST `/datasets/export?format=csv` → CSV columns match `ALL_FEATURE_COLS` + OHLCV | Export contract |
| POST `/features/availability` returns correct counts | Availability endpoint works |
| Backfill → feature build → dataset build chain | Full pipeline integration |

Fixtures: `tests/integration/fixtures/seed_data.sql` inserts synthetic `bar_1d` + `sharadar_daily` + `sharadar_sf1` rows.

## Phase 4 — CI/CD Pipeline

### GitHub Actions (runs on every PR)

Extend `.github/workflows/ci.yml`:

```
Job 1: node-checks        (existing — lint, typecheck, test)
Job 2: python-checks      (existing — add feature-builder to matrix)
Job 3: column-alignment   (NEW — runs Phase 2 tests, no Docker needed)
```

### Self-Hosted Runner on VPS (nightly + manual trigger)

New `.github/workflows/integration.yml`:

```
Job 1: docker-integration  (runs on self-hosted runner labeled 'vps')
  - docker compose -f tests/integration/docker-compose.test.yml up -d
  - wait for health checks
  - seed test data
  - pytest tests/integration/ -v
  - docker compose down
```

Trigger: `workflow_dispatch` + `schedule: cron '0 6 * * *'` (nightly 6am UTC).

### VPS Setup (one-time)

- Provision a lightweight VPS (2 CPU / 4GB RAM is sufficient — just running Postgres + MinIO + 3 Python services)
- Install Docker, GitHub Actions runner
- Register as self-hosted runner with label `vps`
- Store secrets (DATABASE_URL for test, etc.) in GitHub repo settings

## Phase 5 — Harden Existing Tests

| Task | File |
|------|------|
| Add `feature-builder` to CI matrix | `.github/workflows/ci.yml` |
| Add `kaggle-orchestrator`, `dashboard` to CI matrix | `.github/workflows/ci.yml` |
| Remove `continue-on-error: true` from ruff lint step | `.github/workflows/ci.yml` |
| Add `--strict` flag to ruff for new services | `.github/workflows/ci.yml` |
| Pin `continue-on-error` only on torch install, not all deps | `.github/workflows/ci.yml` |

## Implementation Order

1. **Phase 1** — feature-builder unit tests (immediate, high value, zero infra needed)
2. **Phase 2** — column alignment tests (immediate, highest value, zero infra needed)
3. **Phase 5** — CI hardening (quick wins, extend existing ci.yml)
4. **Phase 3** — Docker integration tests (needs docker-compose.test.yml + seed data)
5. **Phase 4** — VPS runner setup (needs VPS provisioned)

Phases 1–3 can be implemented in this session. Phases 4–5 need the VPS provisioned first.

## Files Created/Modified

| Action | Path |
|--------|------|
| CREATE | `services/feature-builder/tests/__init__.py` |
| CREATE | `services/feature-builder/tests/test_feature_builder.py` |
| CREATE | `tests/functional/__init__.py` |
| CREATE | `tests/functional/test_pipeline_column_alignment.py` |
| CREATE | `tests/functional/conftest.py` |
| CREATE | `tests/integration/__init__.py` |
| CREATE | `tests/integration/docker-compose.test.yml` |
| CREATE | `tests/integration/fixtures/seed_data.sql` |
| CREATE | `tests/integration/test_pipeline_integration.py` |
| CREATE | `tests/integration/conftest.py` |
| CREATE | `.github/workflows/integration.yml` |
| MODIFY | `.github/workflows/ci.yml` |

## Out of Scope (Future Work)

- Playwright/UAT browser tests (Phase 2 of testing strategy)
- Frontend Vitest component tests
- Web-UI proxy tests
- Provider smoke tests (live Alpaca/Kaggle)
- Temporal worker tests
