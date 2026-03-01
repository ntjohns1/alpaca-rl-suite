# Alpaca RL Trading Suite

End-to-end research-to-execution platform: ingest market data → engineer features → train DDQN agents → backtest → paper trade via Alpaca.

## Architecture

```
services/
├── api-gateway/        Node/TS  — Fastify reverse proxy + auth middleware
├── auth/               Node/TS  — JWT issue/verify
├── alpaca-adapter/     Node/TS  — Alpaca REST + WebSocket client
├── market-ingest/      Node/TS  — Historical backfill + realtime bar upserts
├── portfolio/          Node/TS  — Position/account snapshots
├── orders/             Node/TS  — Order lifecycle with idempotency keys
├── risk/               Node/TS  — Kill switch + max-loss circuit breaker
├── strategy-runner/    Node/TS  — RTH scheduler → infer → allocate → submit
├── backtest/           Python   — Event-loop engine, cost model, bias guards
├── feature-builder/    Python   — RSI/MACD/ATR/Stoch/UltOsc → parquet/DB
├── dataset-builder/    Python   — Walk-forward splits → MinIO parquet
├── rl-train/           Python   — DDQN training (PyTorch), checkpoints
└── rl-infer/           Python   — FastAPI inference service, policy cache
packages/
├── contracts/          Shared Zod schemas, NATS subjects, DTOs
└── config/             Typed env-var loader
infra/
├── docker-compose.yml  Postgres+TimescaleDB, NATS, MinIO, Grafana, Prometheus
├── migrations/init.sql Full schema with hypertables
└── observability/      Prometheus + OTel collector configs
```

## Quick Start

### 1. Copy and configure environment
```bash
cp .env.example .env
# Edit .env — fill in ALPACA_API_KEY, ALPACA_API_SECRET, JWT_SECRET
```

### 2. Start infrastructure
```bash
pnpm dev:infra
# Postgres+TimescaleDB :5432, NATS :4222, MinIO :9000/:9001,
# Grafana :3100, Prometheus :9090
```

### 3. Install Node dependencies
```bash
pnpm install
```

### 4. Install Python dependencies (per service)
```bash
cd services/feature-builder && pip install -r requirements.txt
cd services/dataset-builder && pip install -r requirements.txt
cd services/backtest         && pip install -r requirements.txt
cd services/rl-train         && pip install -r requirements.txt
cd services/rl-infer         && pip install -r requirements.txt
```

### 5. Build TypeScript packages
```bash
pnpm build
```

### 6. Start Node services (each in separate terminal or use process manager)
```bash
# In separate terminals:
pnpm --filter @alpaca-rl/auth dev
pnpm --filter @alpaca-rl/alpaca-adapter dev
pnpm --filter @alpaca-rl/market-ingest dev
pnpm --filter @alpaca-rl/orders dev
pnpm --filter @alpaca-rl/risk dev
pnpm --filter @alpaca-rl/portfolio dev
pnpm --filter @alpaca-rl/strategy-runner dev
pnpm --filter @alpaca-rl/api-gateway dev
```

### 7. Start Python services
```bash
cd services/feature-builder && python main.py
cd services/dataset-builder && python main.py
cd services/backtest         && python main.py
cd services/rl-train         && python main.py
cd services/rl-infer         && python main.py
```

## Workflow: Research to Paper Trading

### Step 1 — Backfill historical data
```bash
curl -X POST http://localhost:3000/market/backfill \
  -H 'Content-Type: application/json' \
  -d '{"symbols":["AAPL","MSFT"],"startDate":"2020-01-01","endDate":"2024-01-01","timeframe":"1d"}'
```

### Step 2 — Build features
```bash
curl -X POST http://localhost:8002/features/build \
  -H 'Content-Type: application/json' \
  -d '{"symbols":["AAPL","MSFT"],"days":1260}'
```

### Step 3 — Build walk-forward dataset
```bash
curl -X POST http://localhost:8003/datasets/build \
  -H 'Content-Type: application/json' \
  -d '{"name":"aapl-msft-2020-2024","symbols":["AAPL","MSFT"],"start_date":"2020-01-01","end_date":"2024-01-01"}'
```

### Step 4 — Train DDQN agent
```bash
curl -X POST http://localhost:8004/rl/train \
  -H 'Content-Type: application/json' \
  -d '{"name":"aapl-ddqn-v1","symbols":["AAPL"],"maxEpisodes":500}'
```

### Step 5 — Backtest trained policy
```bash
curl -X POST http://localhost:8001/backtest/run \
  -H 'Content-Type: application/json' \
  -d '{"name":"aapl-ddqn-v1-bt","symbols":["AAPL"],"startDate":"2023-01-01","endDate":"2024-01-01","policyId":"<policy-id>"}'
```

### Step 6 — Promote policy and start paper trading
```bash
# Promote policy
curl -X POST http://localhost:8004/rl/policies/<policy-id>/promote

# Start strategy runner
curl -X POST http://localhost:3000/runner/start
```

### Step 7 — Kill switch (emergency stop)
```bash
curl -X POST http://localhost:3000/risk/halt \
  -H 'Content-Type: application/json' \
  -d '{"reason":"manual stop"}'
```

## Key Design Decisions

| Concern | Decision |
|---|---|
| **State vector** | 10 features matching `trading_env.py`: returns (1/2/5/10/21d), RSI, MACD, ATR, Stoch, UltOsc |
| **Actions** | 0=SHORT, 1=HOLD, 2=LONG (matches original notebook) |
| **Cost model** | `trading_cost_bps=10` + `time_cost_bps=1` (configurable per run) |
| **Reproducibility** | Config hash on every training run and backtest; same seed → identical results |
| **Safety** | Kill switch + max daily loss enforced before every order submission |
| **Data lineage** | `dataset_manifest` → `training_run` → `policy_bundle` → `backtest_report` |
| **Trading mode** | `TRADING_MODE=paper` by default; `live` requires explicit env change |

## Environment Variables

See `.env.example` for the full list. Critical variables:

| Variable | Description |
|---|---|
| `ALPACA_API_KEY` | Alpaca API key (never logged) |
| `ALPACA_API_SECRET` | Alpaca API secret (never logged) |
| `ALPACA_BASE_URL` | `https://paper-api.alpaca.markets` for paper trading |
| `DATABASE_URL` | PostgreSQL connection string |
| `JWT_SECRET` | Must be ≥32 chars in production |
| `TRADING_MODE` | `paper` (default) or `live` |
| `MAX_DAILY_LOSS_USD` | Circuit breaker threshold (default: $1000) |
| `KILL_SWITCH_ENABLED` | Start with kill switch active (default: false) |

## Milestones

- [x] **M1** — Monorepo scaffold, infra, DB schema, shared contracts/config, all services
- [ ] **M2** — Alpaca integration tests, order lifecycle E2E
- [ ] **M3** — Realtime bar subscriptions, incremental feature updates
- [ ] **M4** — Backtest validation suite, reproducibility tests
- [ ] **M5** — RL training experiments, hyperparameter sweeps
- [ ] **M6** — Policy → paper trading loop E2E
- [ ] **M7** — Observability hardening, alerting, SLOs
- [ ] **M8** — React dashboard (optional)

## Reference Implementation

The DDQN trading agent is based on:
`22_deep_reinforcement_learning/04_q_learning_for_trading.ipynb`

Key adaptations:
- `DataSource` loads from PostgreSQL/`bar_1d` instead of `assets.h5`
- `gymnasium` replaces legacy `gym`
- PyTorch replaces TensorFlow
- Feature computation uses `ta` (pure Python) instead of TA-Lib
