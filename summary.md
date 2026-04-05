# Testing Pipeline Handoff Summary

## Goal

This work focused on hardening the RL data/training pipeline around the recent SHARADAR 20-feature enrichment, with emphasis on:

- Phase 1: feature-builder unit/API tests
- Phase 2: cross-service column alignment tests
- Phase 3: Docker Compose integration coverage
- CI hardening to run the new checks in controlled environments

The main risk being addressed is silent schema drift between:

- `feature-builder`
- `dataset-builder`
- `kaggle-orchestrator`
- `rl-train/trading_env`
- Kaggle notebooks

## What Was Implemented

### Phase 1: Feature-Builder Tests

Created:

- [services/feature-builder/tests/__init__.py](/Users/noslen/DevProjects/alpaca-rl-suite/services/feature-builder/tests/__init__.py)
- [services/feature-builder/tests/test_feature_builder.py](/Users/noslen/DevProjects/alpaca-rl-suite/services/feature-builder/tests/test_feature_builder.py)

Coverage added:

- 20-column feature generation
- technical vs SHARADAR null-handling
- SHARADAR merge fallback behavior
- state-vector contract
- `_safe_float`
- valuation winsorization
- API-path coverage for:
  - `/features/build`
  - `/features/latest`
  - `/features/availability`
- error-path tests for insufficient data and exception handling

Note:

- This suite is still skipped in the current local shell because the active Python interpreter does not have `fastapi` installed.

### Phase 2: Cross-Service Alignment Tests

Created:

- [tests/functional/__init__.py](/Users/noslen/DevProjects/alpaca-rl-suite/tests/functional/__init__.py)
- [tests/functional/test_pipeline_column_alignment.py](/Users/noslen/DevProjects/alpaca-rl-suite/tests/functional/test_pipeline_column_alignment.py)

Key checks:

- feature-builder output matches `ALL_FEATURE_COLS`
- dataset-builder SQL selects the full 20-feature contract
- kaggle-orchestrator export SQL selects the full 20-feature contract
- `trading_env` aligns with the shared feature contract
- both notebook copies define:
  - `TECHNICAL_COLS`
  - `SHARADAR_COLS`
  - `FEATURE_COLS = TECHNICAL_COLS + SHARADAR_COLS`
- dataset parquet output preserves the full schema

Important test-harness improvements:

- cleaned up `sys.path` handling with temporary restoration
- added kernel-setup notebook coverage
- strengthened notebook contract assertions

### Notebook Alignment Fixes

Updated:

- [kaggle/notebooks/alpaca-rl-training.ipynb](/Users/noslen/DevProjects/alpaca-rl-suite/kaggle/notebooks/alpaca-rl-training.ipynb)
- [kaggle/kernel-setup/alpaca-rl-training.ipynb](/Users/noslen/DevProjects/alpaca-rl-suite/kaggle/kernel-setup/alpaca-rl-training.ipynb)

Changes made:

- updated kernel-setup notebook from stale 10-feature logic to the 20-feature enriched pipeline
- removed `ta`-based recomputation from kernel-setup notebook
- fixed bad JSON indentation in the kernel-setup notebook
- removed hidden `_ret_1d` side-effect by changing `_preprocess()` to return `(features, ret_1d)` explicitly in both notebook copies
- aligned config/feature-version handling with enriched pipeline

### Phase 3: Docker Integration Harness

Created:

- [tests/integration/__init__.py](/Users/noslen/DevProjects/alpaca-rl-suite/tests/integration/__init__.py)
- [tests/integration/conftest.py](/Users/noslen/DevProjects/alpaca-rl-suite/tests/integration/conftest.py)
- [tests/integration/docker-compose.test.yml](/Users/noslen/DevProjects/alpaca-rl-suite/tests/integration/docker-compose.test.yml)
- [tests/integration/fixtures/seed_data.sql](/Users/noslen/DevProjects/alpaca-rl-suite/tests/integration/fixtures/seed_data.sql)
- [tests/integration/test_pipeline_integration.py](/Users/noslen/DevProjects/alpaca-rl-suite/tests/integration/test_pipeline_integration.py)

Coverage target:

- feature build against seeded Postgres data
- feature availability endpoint
- dataset build and MinIO parquet output
- dataset export
- kaggle orchestrator health

Seed data notes:

- seeds `bar_1d`, `sharadar_daily`, and `sharadar_sf1`
- uses business days instead of raw calendar days
- covers `SPY` and `QQQ`

Fixture improvements:

- `built_features` and `built_dataset` are session-scoped

### Docker Packaging Fixes

Updated:

- [services/feature-builder/Dockerfile](/Users/noslen/DevProjects/alpaca-rl-suite/services/feature-builder/Dockerfile)
- [services/dataset-builder/Dockerfile](/Users/noslen/DevProjects/alpaca-rl-suite/services/dataset-builder/Dockerfile)
- [services/rl-train/Dockerfile](/Users/noslen/DevProjects/alpaca-rl-suite/services/rl-train/Dockerfile)
- [tests/integration/docker-compose.test.yml](/Users/noslen/DevProjects/alpaca-rl-suite/tests/integration/docker-compose.test.yml)
- [infra/docker-compose.yml](/Users/noslen/DevProjects/alpaca-rl-suite/infra/docker-compose.yml)

Why this mattered:

- several services import the shared feature contract from `services/shared`
- the original service Dockerfiles only copied their own local directory
- that meant container runtime could drift from local host behavior

What changed:

- build context now includes repo root where needed
- service images now copy `services/shared`
- integration compose was updated to build from the repo root with explicit Dockerfile paths

## CI/CD Changes

Updated:

- [ci.yml](/Users/noslen/DevProjects/alpaca-rl-suite/.github/workflows/ci.yml)

Created:

- [integration.yml](/Users/noslen/DevProjects/alpaca-rl-suite/.github/workflows/integration.yml)

### `ci.yml`

Changes:

- Python test matrix now includes services that actually have tests:
  - `backtest`
  - `dashboard`
  - `dataset-builder`
  - `feature-builder`
  - `kaggle-orchestrator`
  - `rl-train`
- added a lint-only Python matrix for:
  - `rl-infer`
  - `temporal-worker`
  - `web-ui`
- removed blanket `continue-on-error`
- Phase 2 contract job now installs the real dependencies it needs:
  - `pytest`
  - `numpy`
  - `pandas`
  - `pyarrow`
  - `scikit-learn`
  - `ta`
- docker validation now checks both:
  - `infra/docker-compose.yml`
  - `tests/integration/docker-compose.test.yml`

### `integration.yml`

New workflow:

- triggers on:
  - `workflow_dispatch`
  - nightly schedule (`0 6 * * *`)
- runs on:
  - `self-hosted`
  - `linux`
  - `vps`
- steps:
  - install integration test deps
  - validate integration compose
  - `docker compose up -d --build`
  - `pytest tests/integration -q`
  - `docker compose down -v`

## Verification Performed

### Confirmed Passing

- `pytest tests/functional/test_pipeline_column_alignment.py -q`
  - result: `7 passed`

- notebook JSON parses successfully for both notebook files

- `docker compose -f tests/integration/docker-compose.test.yml config --quiet`
  - passed

- `python -m compileall tests/integration`
  - passed earlier during scaffold verification

### Docker Phase 3 Smoke Validation

The Docker stack was brought up successfully and validated via in-network smoke execution:

- seeded Postgres with [seed_data.sql](/Users/noslen/DevProjects/alpaca-rl-suite/tests/integration/fixtures/seed_data.sql)
- verified service health in-network
- ran feature build for `SPY`
- verified feature availability
- confirmed `feature_row` populated in Postgres
- built dataset via dataset-builder
- fetched manifest from MinIO
- verified parquet schema contained the full 20-feature contract plus OHLCV/time/symbol
- verified dataset export contained enriched columns

The temporary integration stack was torn down cleanly after verification.

## Remaining Local Environment Blockers

These are local-shell issues, not repo-structure issues:

- `pytest services/feature-builder/tests/test_feature_builder.py -q`
  - still skipped in the current shell because `fastapi` is missing in the active interpreter

- `pytest tests/integration -q`
  - still fails in the current shell because `boto3` is missing in the active interpreter used by `pytest`

- other conda envs checked were also inconsistent:
  - `tensortown` still lacked `psycopg2`
  - other envs lacked `boto3`

Important:

- the Phase 3 Docker stack itself worked after the repo fixes
- the remaining problems are with which host Python environment is actually being used for local pytest execution

## Files Modified in Current Working Tree

- [ci.yml](/Users/noslen/DevProjects/alpaca-rl-suite/.github/workflows/ci.yml)
- [integration.yml](/Users/noslen/DevProjects/alpaca-rl-suite/.github/workflows/integration.yml)
- [docker-compose.yml](/Users/noslen/DevProjects/alpaca-rl-suite/infra/docker-compose.yml)
- [Dockerfile](/Users/noslen/DevProjects/alpaca-rl-suite/services/dataset-builder/Dockerfile)
- [Dockerfile](/Users/noslen/DevProjects/alpaca-rl-suite/services/feature-builder/Dockerfile)
- [Dockerfile](/Users/noslen/DevProjects/alpaca-rl-suite/services/rl-train/Dockerfile)
- [docker-compose.test.yml](/Users/noslen/DevProjects/alpaca-rl-suite/tests/integration/docker-compose.test.yml)

There are also earlier-added test and notebook changes already present in the repo from this workstream, even if they are no longer showing as unstaged in the current `git status`.

## Recommended Next Steps For The VPS / Self-Hosted Runner Agent

### Immediate

1. Stand up a self-hosted GitHub Actions runner with labels:
   - `self-hosted`
   - `linux`
   - `vps`

2. Ensure the VPS has:
   - Docker
   - Docker Compose v2
   - Python 3.11
   - enough disk for Docker builds

3. Validate the new workflow:
   - [integration.yml](/Users/noslen/DevProjects/alpaca-rl-suite/.github/workflows/integration.yml)

4. Run:
   - `docker compose -f tests/integration/docker-compose.test.yml up -d --build`
   - `pytest tests/integration -q`

### On The VPS, Watch For

- whether the self-hosted runner user can access Docker without sudo issues
- whether GitHub runner has enough timeout budget for image builds on first run
- whether network egress to Docker Hub is fast enough for the first cold build
- whether MinIO/Postgres startup timing needs a longer wait window in `tests/integration/conftest.py`

### Likely Follow-Ups

- add a documented bootstrap step for the self-hosted runner
- decide whether the integration workflow should upload logs/artifacts on failure
- decide whether nightly integration should also archive MinIO manifests or parquet samples for debugging

## Good Handoff Entry Points

If another agent is picking this up in a different environment, the best files to inspect first are:

- [tests/testing-cicd-pipeline-correctness-ffa050.md](/Users/noslen/DevProjects/alpaca-rl-suite/tests/testing-cicd-pipeline-correctness-ffa050.md)
- [ci.yml](/Users/noslen/DevProjects/alpaca-rl-suite/.github/workflows/ci.yml)
- [integration.yml](/Users/noslen/DevProjects/alpaca-rl-suite/.github/workflows/integration.yml)
- [docker-compose.test.yml](/Users/noslen/DevProjects/alpaca-rl-suite/tests/integration/docker-compose.test.yml)
- [test_pipeline_integration.py](/Users/noslen/DevProjects/alpaca-rl-suite/tests/integration/test_pipeline_integration.py)
- [test_pipeline_column_alignment.py](/Users/noslen/DevProjects/alpaca-rl-suite/tests/functional/test_pipeline_column_alignment.py)

## Bottom Line

The highest-risk part of the pipeline, the SHARADAR-enriched 20-feature contract, now has:

- service-level tests
- cross-service contract checks
- notebook alignment checks
- a Docker integration harness
- CI workflows prepared for both PR-time and nightly integration validation

The main remaining task is operational:

- stand up the self-hosted VPS runner
- run the new integration workflow in that environment
- optionally normalize local Python env usage for developers who want to run the same suites outside CI
