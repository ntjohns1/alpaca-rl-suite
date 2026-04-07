# Alpaca RL Suite Test Matrix

This document translates the current testing strategy into a concrete, executable plan for validating the product at the levels that matter: service correctness, cross-service integration, end-to-end functional behavior, and operator-facing UAT.

It is intentionally biased toward proving the core product promise:

1. Ingest market data
2. Build features
3. Build datasets
4. Train policies
5. Backtest policies
6. Approve and promote policies
7. Run safely in paper trading

## Goals

- Prove the system behaves correctly across service boundaries, not just inside individual modules.
- Catch regressions in the user-visible workflow through the React app.
- Keep PR feedback fast while still running deeper functional/UAT coverage on a schedule.
- Prefer deterministic tests with fake external providers over brittle live-provider tests.

## Test Layers

| Layer | Purpose | Primary Tools | When |
|---|---|---|---|
| Unit | Validate pure logic and local service behavior | `pytest`, `vitest` | PR |
| Contract / API integration | Validate request/response shape and boundary assumptions | `pytest`, `vitest`, FastAPI test client, HTTP mocks | PR |
| Functional integration | Validate multi-service workflows in Docker with real infra | `pytest`, Docker Compose | PR for slim subset, Nightly for broad set |
| UAT / browser E2E | Validate what an operator actually does in the React UI | `Playwright` | PR for golden paths, Nightly for broad coverage |
| Provider smoke | Validate live Alpaca / Kaggle / Keycloak connectivity | `pytest`, Playwright, provider sandbox creds | Nightly / manual |

## Environment Strategy

Use three standard environments:

### 1. Local Fast Feedback

- Scope: unit tests, contract tests, component tests
- Infra: mocks only
- Runtime target: under 5-8 minutes

### 2. Hermetic Integration

- Scope: functional integration and UI golden paths
- Infra: Docker Compose with Postgres, MinIO, NATS, web-ui, backend services
- External providers: replaced by deterministic fakes where possible
- Runtime target: under 15-20 minutes on CI

### 3. Provider-Backed Smoke

- Scope: live Alpaca paper endpoints, Kaggle orchestration, Keycloak/OIDC verification
- Infra: Docker Compose plus test credentials
- Runtime target: nightly or manually triggered only

## Execution Policy

### Required on Every PR

- Existing Python and Node unit tests
- New frontend component tests
- Contract tests for service APIs
- Hermetic functional tests for:
  - dataset build happy path
  - training submission and status progression
  - approval/promote happy path
  - backtest happy path
- 2-4 Playwright golden-path UAT tests

### Nightly

- Full functional workflow suite
- Failure-path matrix
- Reproducibility checks
- Live provider smoke tests
- Observability / degradation checks

## Core Workflow Matrix

| Workflow | User Value | Primary Risks | Test Layers | PR | Nightly |
|---|---|---|---|---|---|
| Market backfill | Historical data enters system correctly | bad mapping, duplicates, missing rows, provider drift | unit, integration, functional | Yes | Yes |
| Feature computation | Indicators are available and aligned with bars | wrong date alignment, NaNs, partial coverage | unit, integration, functional | Yes | Yes |
| Dataset build | Walk-forward dataset matches expectations | lookahead leakage, bad split logic, missing artifacts | unit, integration, functional, UAT | Yes | Yes |
| Training | Job submission and tracking work | wrong config persistence, bad status transitions, hidden failure | unit, integration, functional, UAT | Yes | Yes |
| Backtest | Reported metrics and artifacts are trustworthy | metric drift, artifact mismatch, bad aggregation | unit, integration, functional, UAT | Yes | Yes |
| Approval / promotion | Only valid policies can move forward | status bugs, accidental promotion, missing audit trail | integration, functional, UAT | Yes | Yes |
| Strategy runner / paper trading | System can execute policy safely | unsafe submission, kill-switch bypass, bad dependency handling | unit, functional, provider smoke | Slim | Yes |
| Monitoring / health | Operators understand system state | false green, poor degradation UX, broken links | integration, UAT | Slim | Yes |
| Auth / OIDC | Access control and UX are correct | broken login flow, stale tokens, proxy auth bugs | integration, UAT, provider smoke | Slim | Yes |

## Service Coverage Matrix

| Service | Current State | Gaps | Add Next |
|---|---|---|---|
| `market-ingest` | Some tests | No broad functional workflow coverage | API integration + fake-provider backfill functional tests |
| `feature-builder` | No visible tests | High-risk data transformation path uncovered | unit tests for feature generation + API integration |
| `dataset-builder` | Good unit base | No full workflow validation with feature availability checks | functional dataset flow tests |
| `rl-train` | Good unit/API base | Limited end-to-end job lifecycle proof | functional training lifecycle tests |
| `backtest` | Good unit/API base | Needs trust-building workflow tests and reproducibility checks | functional backtest + nightly reproducibility |
| `kaggle-orchestrator` | Good service tests | Limited UI and lineage validation | functional approval flow tests |
| `rl-infer` | No visible tests | Inference boundary uncovered | API integration + runner interaction tests |
| `risk` | Some unit tests | Needs cross-service safety proof | runner + orders functional tests |
| `orders` | Some unit tests | Needs idempotency and risk-gate workflow proof | functional order path tests |
| `portfolio` | No visible tests | Snapshot sync and API behavior uncovered | API integration tests |
| `strategy-runner` | Some unit tests | No end-to-end orchestration proof | functional runner tests |
| `api-gateway` | No visible tests | High-risk routing/auth boundary uncovered | route contract tests |
| `web-ui` backend proxy | No visible tests | High-risk auth proxy/error translation uncovered | FastAPI proxy tests |
| React frontend | No tests | No automated UAT or component coverage | Vitest/RTL + Playwright |
| `temporal-worker` | No visible tests | Workflow orchestration uncovered | workflow tests with mocked activities |

## Proposed Directory Layout

### Frontend Component and Browser Tests

```text
services/web-ui/frontend/
  src/
    __tests__/
      app-shell.test.tsx
      training-page.test.tsx
      approvals-page.test.tsx
      policies-page.test.tsx
      dataset-builder.test.tsx
      monitoring-page.test.tsx
  playwright.config.ts
  tests/
    e2e/
      auth-login.spec.ts
      dataset-build.spec.ts
      training-lifecycle.spec.ts
      approval-promote.spec.ts
      monitoring-health.spec.ts
  test/
    msw/
      handlers.ts
      server.ts
```

### Backend Functional Tests

```text
tests/
  functional/
    conftest.py
    fixtures/
      fake_alpaca.py
      fake_kaggle.py
      seed_data.py
    test_market_to_features_flow.py
    test_dataset_build_flow.py
    test_training_and_approval_flow.py
    test_backtest_and_artifacts_flow.py
    test_policy_promotion_flow.py
    test_runner_safety_flow.py
    test_monitoring_degraded_state.py
    test_auth_proxy_flow.py
  smoke/
    test_alpaca_paper_smoke.py
    test_kaggle_smoke.py
    test_keycloak_smoke.py
```

### Missing Service-Level Suites

```text
services/feature-builder/tests/test_feature_builder.py
services/rl-infer/tests/test_rl_infer_api.py
services/portfolio/tests/test_portfolio_api.py
services/api-gateway/src/__tests__/routes.test.ts
services/web-ui/tests/test_proxy.py
services/temporal-worker/tests/test_workflows.py
services/auth/src/__tests__/auth.test.ts
```

## Feature-by-Feature Matrix

### 1. Market Backfill

| Scenario | Layer | Tooling | Proposed File | PR | Nightly |
|---|---|---|---|---|---|
| Request validation rejects bad symbols/date ranges | API integration | `pytest`, FastAPI/HTTP client | `tests/functional/test_market_to_features_flow.py` | Yes | Yes |
| Backfill stores sane OHLCV rows | Functional | `pytest`, Compose, fake Alpaca | `tests/functional/test_market_to_features_flow.py` | Yes | Yes |
| Upsert prevents duplicates | Functional | `pytest`, DB assertions | `tests/functional/test_market_to_features_flow.py` | Yes | Yes |
| Provider schema drift smoke | Provider smoke | `pytest` | `tests/smoke/test_alpaca_paper_smoke.py` | No | Yes |

Acceptance criteria:
- Requested bars exist in DB for all requested symbols.
- OHLCV fields are sane and in expected ranges.
- Re-running identical backfill does not duplicate rows.

### 2. Feature Computation

| Scenario | Layer | Tooling | Proposed File | PR | Nightly |
|---|---|---|---|---|---|
| Indicator generation handles clean market data | Unit | `pytest` | `services/feature-builder/tests/test_feature_builder.py` | Yes | Yes |
| Missing/partial source data handled predictably | Unit | `pytest` | `services/feature-builder/tests/test_feature_builder.py` | Yes | Yes |
| Feature rows align to bar dates without lookahead | Integration | `pytest` | `services/feature-builder/tests/test_feature_builder.py` | Yes | Yes |
| End-to-end feature compute after backfill | Functional | `pytest`, Compose | `tests/functional/test_market_to_features_flow.py` | Yes | Yes |

Acceptance criteria:
- Feature rows exist for each requested symbol/date range.
- No NaNs or infs in persisted features unless explicitly allowed.
- No feature timestamp leads the source price timestamp.

### 3. Dataset Build

| Scenario | Layer | Tooling | Proposed File | PR | Nightly |
|---|---|---|---|---|---|
| Split logic avoids lookahead | Unit | existing `pytest` | existing dataset-builder tests | Yes | Yes |
| Build persists manifest and artifacts | Functional | `pytest`, MinIO assertions | `tests/functional/test_dataset_build_flow.py` | Yes | Yes |
| UI auto-computes features when needed | UAT | `Playwright`, fake APIs | `services/web-ui/frontend/tests/e2e/dataset-build.spec.ts` | Yes | Yes |
| UI handles missing bars and offers backfill path | UAT | `Playwright` | `services/web-ui/frontend/tests/e2e/dataset-build.spec.ts` | Yes | Yes |

Acceptance criteria:
- Dataset manifest exists in DB.
- Expected train/test parquet artifacts exist in MinIO.
- UI shows success state and new dataset row.

### 4. Training

| Scenario | Layer | Tooling | Proposed File | PR | Nightly |
|---|---|---|---|---|---|
| API validates payloads and persists job | Integration | existing `pytest` + additions | existing RL train tests | Yes | Yes |
| Job transitions through expected statuses | Functional | `pytest`, Compose | `tests/functional/test_training_and_approval_flow.py` | Yes | Yes |
| Failed training surfaces useful error | Functional | `pytest` | `tests/functional/test_training_and_approval_flow.py` | Yes | Yes |
| Training page creates/cancels job correctly | UAT | `Playwright` | `services/web-ui/frontend/tests/e2e/training-lifecycle.spec.ts` | Yes | Yes |

Acceptance criteria:
- Training job record exists with correct config hash and status history.
- Policy artifact and metadata are produced on success.
- UI reflects state transitions without refresh bugs.

### 5. Backtest

| Scenario | Layer | Tooling | Proposed File | PR | Nightly |
|---|---|---|---|---|---|
| Metrics are deterministic for fixed seed/data | Unit | existing `pytest` + nightly seed test | `services/backtest/tests/test_reproducibility.py` | No | Yes |
| Report and chart artifacts are created | Functional | `pytest`, MinIO assertions | `tests/functional/test_backtest_and_artifacts_flow.py` | Yes | Yes |
| Failed backtests expose actionable errors | Functional | `pytest` | `tests/functional/test_backtest_and_artifacts_flow.py` | Yes | Yes |
| UI displays backtest result and charts | UAT | `Playwright` | `services/web-ui/frontend/tests/e2e/approval-promote.spec.ts` | Slim | Yes |

Acceptance criteria:
- Backtest report row exists and links to generated artifacts.
- Aggregated metrics match underlying per-symbol metrics.
- Seeded reproducibility run stays within expected tolerance.

### 6. Approval and Promotion

| Scenario | Layer | Tooling | Proposed File | PR | Nightly |
|---|---|---|---|---|---|
| Pending job can be approved and creates/promotes policy | Functional | `pytest`, Compose | `tests/functional/test_policy_promotion_flow.py` | Yes | Yes |
| Invalid states cannot be approved/promoted | Integration | `pytest` | `tests/functional/test_policy_promotion_flow.py` | Yes | Yes |
| Approvals page shows metrics and decision actions | UAT | `Playwright` | `services/web-ui/frontend/tests/e2e/approval-promote.spec.ts` | Yes | Yes |
| Policies page reflects promoted status correctly | UAT | `Playwright` | `services/web-ui/frontend/tests/e2e/approval-promote.spec.ts` | Yes | Yes |

Acceptance criteria:
- Only valid statuses can transition.
- Audit fields are persisted.
- Promoted policy is the one used by downstream services.

### 7. Strategy Runner and Safety

| Scenario | Layer | Tooling | Proposed File | PR | Nightly |
|---|---|---|---|---|---|
| Kill switch blocks order submission | Functional | `pytest`, Compose | `tests/functional/test_runner_safety_flow.py` | Slim | Yes |
| Daily loss guard blocks order submission | Functional | `pytest` | `tests/functional/test_runner_safety_flow.py` | Slim | Yes |
| Missing dependency degrades safely | Functional | `pytest` | `tests/functional/test_runner_safety_flow.py` | Slim | Yes |
| Paper smoke with fake Alpaca order submission | Functional | `pytest` | `tests/functional/test_runner_safety_flow.py` | Slim | Yes |
| Live paper smoke against Alpaca sandbox | Provider smoke | `pytest` | `tests/smoke/test_alpaca_paper_smoke.py` | No | Yes |

Acceptance criteria:
- No order is submitted when risk gate says no.
- Orders are idempotent where expected.
- Failure modes are visible in logs and service health.

### 8. Monitoring and Degradation

| Scenario | Layer | Tooling | Proposed File | PR | Nightly |
|---|---|---|---|---|---|
| Dashboard aggregates service health correctly | Integration | existing `pytest` + additions | existing dashboard tests | Yes | Yes |
| UI renders degraded service states | UAT | `Playwright`, MSW | `services/web-ui/frontend/tests/e2e/monitoring-health.spec.ts` | Slim | Yes |
| Broken Grafana URL or unhealthy service is operator-visible | UAT | `Playwright` | `services/web-ui/frontend/tests/e2e/monitoring-health.spec.ts` | Slim | Yes |

Acceptance criteria:
- Degraded services are not shown as healthy.
- Operator can navigate to Grafana when available.
- Error messages are understandable.

### 9. Authentication and Proxying

| Scenario | Layer | Tooling | Proposed File | PR | Nightly |
|---|---|---|---|---|---|
| Unauthenticated users see login page | Component/UAT | `Vitest`, `Playwright` | `services/web-ui/frontend/src/__tests__/app-shell.test.tsx`, `auth-login.spec.ts` | Yes | Yes |
| Authenticated users can access proxied APIs | Integration | `pytest` | `services/web-ui/tests/test_proxy.py` | Yes | Yes |
| Proxy preserves method/body/query/error mapping | Integration | `pytest` | `services/web-ui/tests/test_proxy.py` | Yes | Yes |
| Real Keycloak config/connectivity smoke | Provider smoke | `pytest`, Playwright | `tests/smoke/test_keycloak_smoke.py` | No | Yes |

Acceptance criteria:
- Unauthorized access is blocked.
- Authorization header is forwarded correctly.
- Backend errors are translated consistently for the frontend.

## Frontend Component Test Matrix

Use `Vitest + React Testing Library + MSW`.

| Component / Page | What to Validate | Proposed File |
|---|---|---|
| App shell | login vs authenticated shell, route rendering, overview fetch gating | `services/web-ui/frontend/src/__tests__/app-shell.test.tsx` |
| Training page | list rendering, create job, cancel job, loading/error states | `services/web-ui/frontend/src/__tests__/training-page.test.tsx` |
| Approvals page | pending jobs render, approve/reject actions, empty state | `services/web-ui/frontend/src/__tests__/approvals-page.test.tsx` |
| Policies page | approval/promote/delete actions and conditional buttons | `services/web-ui/frontend/src/__tests__/policies-page.test.tsx` |
| Dataset builder | symbol selection, validation, feature check, auto-compute branch, build success/failure | `services/web-ui/frontend/src/__tests__/dataset-builder.test.tsx` |
| Monitoring page | health list, refresh behavior, Grafana link, degraded states | `services/web-ui/frontend/src/__tests__/monitoring-page.test.tsx` |

## Golden UAT Journeys

These are the highest-value Playwright tests and should be stable enough for PR use.

### PR Golden Paths

1. `dataset-build.spec.ts`
Creates a dataset from the UI with fake provider responses and verifies the dataset appears in the list.

2. `training-lifecycle.spec.ts`
Starts a training job, verifies it appears in Training, and verifies cancellation or successful completion state.

3. `approval-promote.spec.ts`
Shows a completed job in Approvals, approves it, and verifies the resulting policy is visible/promoted in Policies.

4. `auth-login.spec.ts`
Verifies login screen for unauthenticated state and shell access for authenticated state.

### Nightly Expanded Journeys

1. Backfill missing data from the UI, then continue to dataset creation.
2. Failed training job shows useful error and does not appear promotable.
3. Backtest artifact and charts are visible after completion.
4. Monitoring shows one service degraded and one healthy.
5. Risk kill switch blocks downstream runner behavior.

## Recommended Tooling Additions

### Frontend

- `vitest`
- `@testing-library/react`
- `@testing-library/user-event`
- `@testing-library/jest-dom`
- `msw`
- `playwright`

### Backend / Functional

- `pytest-xdist` for parallelism where safe
- `responses` or `respx` for provider mocking
- `testcontainers` as an alternative to full Compose for selected suites

## CI Matrix Recommendation

### Job 1: Fast Static Checks

- Node lint/typecheck
- Python lint

### Job 2: Unit and Contract

- existing Python service tests
- existing Node service tests
- frontend component tests
- proxy/API contract tests

### Job 3: Hermetic Functional

- spin up Compose
- run `tests/functional/` against fake providers

### Job 4: Browser UAT

- run Playwright golden paths

### Job 5: Nightly Extended

- full functional suite
- reproducibility checks
- provider smoke

## Initial Implementation Backlog

Build this in order:

1. Add frontend test harness and component tests.
2. Add `services/web-ui/tests/test_proxy.py`.
3. Add service tests for `feature-builder`, `rl-infer`, `portfolio`, and `temporal-worker`.
4. Add `tests/functional/` with fake Alpaca and fake Kaggle fixtures.
5. Add Playwright golden-path tests.
6. Tighten CI to fail on missing or skipped critical suites.

## Definition of Done

The testing plan is in good shape when all of the following are true:

- Every critical workflow in the README has at least one functional test.
- Every critical user flow in the React UI has at least one Playwright test.
- Every high-risk orchestration boundary has contract tests.
- CI runs a trustworthy PR subset and a broader nightly suite.
- Live provider dependencies are tested separately from hermetic product behavior.

## Current Highest-Priority Gaps

If you only address a few things first, do these:

1. Add frontend tests for the React app.
2. Add UAT for dataset build, training, and approval/promote.
3. Add tests for the web-ui backend proxy.
4. Add functional tests for the full dataset → training → approval → promotion chain.
