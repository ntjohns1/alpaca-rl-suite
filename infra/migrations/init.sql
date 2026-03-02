-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ─────────────────────────────────────────
-- Market data tables
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bar_1m (
    time        TIMESTAMPTZ     NOT NULL,
    symbol      TEXT            NOT NULL,
    open        NUMERIC(18,6)   NOT NULL,
    high        NUMERIC(18,6)   NOT NULL,
    low         NUMERIC(18,6)   NOT NULL,
    close       NUMERIC(18,6)   NOT NULL,
    volume      BIGINT          NOT NULL,
    vwap        NUMERIC(18,6),
    trade_count INTEGER,
    PRIMARY KEY (time, symbol)
);
SELECT create_hypertable('bar_1m', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_bar_1m_symbol_time ON bar_1m (symbol, time DESC);

CREATE TABLE IF NOT EXISTS bar_1d (
    time        TIMESTAMPTZ     NOT NULL,
    symbol      TEXT            NOT NULL,
    open        NUMERIC(18,6)   NOT NULL,
    high        NUMERIC(18,6)   NOT NULL,
    low         NUMERIC(18,6)   NOT NULL,
    close       NUMERIC(18,6)   NOT NULL,
    volume      BIGINT          NOT NULL,
    vwap        NUMERIC(18,6),
    trade_count INTEGER,
    PRIMARY KEY (time, symbol)
);
SELECT create_hypertable('bar_1d', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_bar_1d_symbol_time ON bar_1d (symbol, time DESC);

-- ─────────────────────────────────────────
-- Feature store
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS feature_row (
    time        TIMESTAMPTZ     NOT NULL,
    symbol      TEXT            NOT NULL,
    ret_1d      NUMERIC(12,8),
    ret_2d      NUMERIC(12,8),
    ret_5d      NUMERIC(12,8),
    ret_10d     NUMERIC(12,8),
    ret_21d     NUMERIC(12,8),
    rsi         NUMERIC(10,4),
    macd        NUMERIC(12,8),
    atr         NUMERIC(12,6),
    stoch       NUMERIC(10,4),
    ultosc      NUMERIC(10,4),
    parquet_ref TEXT,
    PRIMARY KEY (time, symbol)
);
SELECT create_hypertable('feature_row', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_feature_row_symbol ON feature_row (symbol, time DESC);

-- ─────────────────────────────────────────
-- Dataset manifests
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dataset_manifest (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    name            TEXT            NOT NULL,
    symbols         TEXT[]          NOT NULL,
    start_date      DATE            NOT NULL,
    end_date        DATE            NOT NULL,
    n_splits        INTEGER         NOT NULL,
    split_type      TEXT            NOT NULL DEFAULT 'walk_forward',
    s3_path         TEXT            NOT NULL,
    feature_version TEXT            NOT NULL,
    metadata        JSONB
);

-- ─────────────────────────────────────────
-- Orders
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS order_event (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    idempotency_key TEXT            UNIQUE NOT NULL,
    alpaca_order_id TEXT,
    symbol          TEXT            NOT NULL,
    side            TEXT            NOT NULL CHECK (side IN ('buy','sell')),
    qty             NUMERIC(18,8)   NOT NULL,
    notional        NUMERIC(18,2),
    order_type      TEXT            NOT NULL DEFAULT 'limit',
    time_in_force   TEXT            NOT NULL DEFAULT 'day',
    limit_price     NUMERIC(18,6),
    status          TEXT            NOT NULL DEFAULT 'pending',
    filled_qty      NUMERIC(18,8)   DEFAULT 0,
    filled_avg_price NUMERIC(18,6),
    commission      NUMERIC(12,6)   DEFAULT 0,
    raw_event       JSONB,
    trace_id        TEXT
);
CREATE INDEX IF NOT EXISTS idx_order_event_symbol ON order_event (symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_order_event_status ON order_event (status);
CREATE INDEX IF NOT EXISTS idx_order_event_alpaca_id ON order_event (alpaca_order_id);

-- ─────────────────────────────────────────
-- Portfolio snapshots
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS position_snapshot (
    id              UUID            DEFAULT gen_random_uuid(),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    symbol          TEXT            NOT NULL,
    qty             NUMERIC(18,8)   NOT NULL,
    avg_entry_price NUMERIC(18,6)   NOT NULL,
    market_value    NUMERIC(18,2),
    unrealized_pl   NUMERIC(18,2),
    unrealized_plpc NUMERIC(12,8),
    current_price   NUMERIC(18,6),
    trace_id        TEXT,
    PRIMARY KEY (created_at, id)
);
SELECT create_hypertable('position_snapshot', 'created_at', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS account_snapshot (
    id              UUID            DEFAULT gen_random_uuid(),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    equity          NUMERIC(18,2)   NOT NULL,
    cash            NUMERIC(18,2)   NOT NULL,
    buying_power    NUMERIC(18,2)   NOT NULL,
    portfolio_value NUMERIC(18,2)   NOT NULL,
    daily_pl        NUMERIC(18,2),
    raw_account     JSONB,
    PRIMARY KEY (created_at, id)
);
SELECT create_hypertable('account_snapshot', 'created_at', if_not_exists => TRUE);

-- ─────────────────────────────────────────
-- RL Training runs & policy registry
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS training_run (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    name            TEXT            NOT NULL,
    config_hash     TEXT            NOT NULL,
    config          JSONB           NOT NULL,
    dataset_id      UUID            REFERENCES dataset_manifest(id),
    status          TEXT            NOT NULL DEFAULT 'pending'
                                    CHECK (status IN ('pending','running','completed','failed')),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    metrics         JSONB,
    artifact_path   TEXT,
    error           TEXT
);
CREATE INDEX IF NOT EXISTS idx_training_run_status ON training_run (status);

CREATE TABLE IF NOT EXISTS policy_bundle (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    training_run_id UUID            NOT NULL REFERENCES training_run(id),
    name            TEXT            NOT NULL,
    version         TEXT            NOT NULL,
    s3_path         TEXT            NOT NULL,
    config          JSONB           NOT NULL,
    metrics         JSONB,
    promoted        BOOLEAN         NOT NULL DEFAULT FALSE,
    promoted_at     TIMESTAMPTZ,
    promoted_by     TEXT
);
CREATE INDEX IF NOT EXISTS idx_policy_bundle_promoted ON policy_bundle (promoted, created_at DESC);

-- ─────────────────────────────────────────
-- Risk / kill switch state
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS risk_state (
    id              SERIAL          PRIMARY KEY,
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    kill_switch     BOOLEAN         NOT NULL DEFAULT FALSE,
    daily_loss_usd  NUMERIC(18,2)   NOT NULL DEFAULT 0,
    max_daily_loss  NUMERIC(18,2)   NOT NULL DEFAULT 1000,
    reason          TEXT
);
INSERT INTO risk_state (kill_switch, daily_loss_usd, max_daily_loss)
VALUES (FALSE, 0, 1000)
ON CONFLICT DO NOTHING;

-- ─────────────────────────────────────────
-- Backtest reports
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS backtest_report (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    name            TEXT            NOT NULL,
    config          JSONB           NOT NULL,
    config_hash     TEXT            NOT NULL,
    dataset_id      UUID            REFERENCES dataset_manifest(id),
    policy_id       UUID            REFERENCES policy_bundle(id),
    status          TEXT            NOT NULL DEFAULT 'pending',
    metrics         JSONB,
    artifact_path   TEXT,
    error           TEXT
);
