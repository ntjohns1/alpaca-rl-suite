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
-- Singleton table: id is fixed at 1. The CHECK constraint and explicit id in
-- INSERT prevent drift from container restarts generating extra rows (which
-- caused every UPDATE to touch all rows while getState() only read the first).
CREATE TABLE IF NOT EXISTS risk_state (
    id                          INTEGER         PRIMARY KEY CHECK (id = 1),
    updated_at                  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    kill_switch                 BOOLEAN         NOT NULL DEFAULT FALSE,
    daily_loss_usd              NUMERIC(18,2)   NOT NULL DEFAULT 0,
    max_daily_loss              NUMERIC(18,2)   NOT NULL DEFAULT 1000,
    portfolio_value             NUMERIC(18,2),
    portfolio_value_updated_at  TIMESTAMPTZ,
    reason                      TEXT
);
-- Idempotent column adds for environments where init.sql ran before these columns existed.
-- The portfolio_value ADD can be removed once all environments have been migrated past
-- the first ALPCA-8 deploy (approx. 2026-06-01).
ALTER TABLE risk_state ADD COLUMN IF NOT EXISTS portfolio_value NUMERIC(18,2);
ALTER TABLE risk_state ADD COLUMN IF NOT EXISTS portfolio_value_updated_at TIMESTAMPTZ;

-- ── Migration: converge existing multi-row environments to the singleton ──────
-- CREATE TABLE above is a no-op on existing databases that have the old SERIAL
-- primary key schema. The following block cleans up any drift from container
-- restarts that generated extra rows under the old `ON CONFLICT DO NOTHING`
-- (which had no conflict target, so SERIAL-generated ids never conflicted).
DO $$
BEGIN
  -- Step 1: Ensure a row with id=1 exists. If the canonical row has a
  -- different id (e.g. id=2 from a fresh container), copy its state into id=1.
  -- Use ORDER BY updated_at DESC, not id ASC: on a drifted database the
  -- lowest-id row may be the stale initial seed while higher-id rows carry
  -- the actually-current state (they were being mutated on every UPDATE).
  IF NOT EXISTS (SELECT 1 FROM risk_state WHERE id = 1) THEN
    INSERT INTO risk_state
      (id, kill_switch, daily_loss_usd, max_daily_loss,
       portfolio_value, portfolio_value_updated_at, reason)
    SELECT 1, kill_switch, daily_loss_usd, max_daily_loss,
           portfolio_value, portfolio_value_updated_at, reason
    FROM   risk_state
    ORDER  BY updated_at DESC
    LIMIT  1;
  END IF;

  -- Step 2: Remove every row that is not the singleton.
  DELETE FROM risk_state WHERE id <> 1;

  -- Step 3: Add the CHECK constraint if it does not already exist.
  -- The DELETE above guarantees no row can violate CHECK (id = 1) at this point.
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE  conname = 'risk_state_singleton'
    AND    conrelid = 'risk_state'::regclass
  ) THEN
    EXECUTE 'ALTER TABLE risk_state ADD CONSTRAINT risk_state_singleton CHECK (id = 1)';
  END IF;
END $$;

-- Remove the SERIAL sequence and its column default so that a future INSERT
-- without an explicit id cannot silently generate a value and violate CHECK (id=1).
-- Idempotent on fresh databases (the sequence may not exist).
ALTER TABLE risk_state ALTER COLUMN id DROP DEFAULT;
DROP SEQUENCE IF EXISTS risk_state_id_seq;

INSERT INTO risk_state (id, kill_switch, daily_loss_usd, max_daily_loss)
VALUES (1, FALSE, 0, 1000)
ON CONFLICT (id) DO NOTHING;

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
