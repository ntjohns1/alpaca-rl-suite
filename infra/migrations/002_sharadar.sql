-- ─────────────────────────────────────────
-- SHARADAR data integration
-- Migration 002: Add SHARADAR-specific columns and tables
-- ─────────────────────────────────────────

-- 1. Extend bar_1d with SHARADAR-specific columns
ALTER TABLE bar_1d
    ADD COLUMN IF NOT EXISTS closeadj    NUMERIC(18,6),
    ADD COLUMN IF NOT EXISTS closeunadj  NUMERIC(18,6),
    ADD COLUMN IF NOT EXISTS source      TEXT DEFAULT 'alpaca';

-- Backfill existing rows
UPDATE bar_1d SET source = 'alpaca' WHERE source IS NULL;

-- Index for source filtering
CREATE INDEX IF NOT EXISTS idx_bar_1d_source ON bar_1d (source);

-- ─────────────────────────────────────────
-- 2. SHARADAR Daily Metrics (time-series)
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sharadar_daily (
    ticker       TEXT           NOT NULL,
    date         DATE           NOT NULL,
    lastupdated  DATE,
    ev           NUMERIC(18,2),
    evebit       DOUBLE PRECISION,
    evebitda     DOUBLE PRECISION,
    marketcap    NUMERIC(18,2),
    pb           DOUBLE PRECISION,
    pe           DOUBLE PRECISION,
    ps           DOUBLE PRECISION,
    PRIMARY KEY (date, ticker)
);
SELECT create_hypertable('sharadar_daily', 'date', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_sharadar_daily_ticker ON sharadar_daily (ticker, date DESC);

-- ─────────────────────────────────────────
-- 3. SHARADAR Fundamentals (SF1)
-- Key typed columns + JSONB extras for the ~100 remaining fields
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sharadar_sf1 (
    ticker         TEXT           NOT NULL,
    dimension      TEXT           NOT NULL,
    calendardate   DATE           NOT NULL,
    datekey        DATE,
    reportperiod   DATE,
    fiscalperiod   TEXT,
    lastupdated    DATE,
    -- Key fundamentals (typed for fast queries)
    revenue        NUMERIC(18,2),
    netinc         NUMERIC(18,2),
    netinccmn      NUMERIC(18,2),
    gp             NUMERIC(18,2),
    ebit           NUMERIC(18,2),
    ebitda         NUMERIC(18,2),
    eps            DOUBLE PRECISION,
    epsdil         DOUBLE PRECISION,
    debt           NUMERIC(18,2),
    equity         NUMERIC(18,2),
    assets         NUMERIC(18,2),
    cashneq        NUMERIC(18,2),
    marketcap      NUMERIC(18,2),
    ev             NUMERIC(18,2),
    pe             DOUBLE PRECISION,
    pb             DOUBLE PRECISION,
    ps             DOUBLE PRECISION,
    roe            DOUBLE PRECISION,
    roa            DOUBLE PRECISION,
    roic           DOUBLE PRECISION,
    divyield       DOUBLE PRECISION,
    fcf            NUMERIC(18,2),
    -- All remaining columns stored as JSONB
    extras         JSONB,
    PRIMARY KEY (calendardate, ticker, dimension)
);
CREATE INDEX IF NOT EXISTS idx_sharadar_sf1_ticker ON sharadar_sf1 (ticker, calendardate DESC);
CREATE INDEX IF NOT EXISTS idx_sharadar_sf1_dimension ON sharadar_sf1 (dimension);

-- ─────────────────────────────────────────
-- 4. SHARADAR Tickers (metadata, not time-series)
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sharadar_tickers (
    "table"          TEXT,
    permaticker      INTEGER,
    ticker           TEXT           PRIMARY KEY,
    name             TEXT,
    exchange         TEXT,
    isdelisted       TEXT,
    category         TEXT,
    cusips           TEXT,
    siccode          TEXT,
    sicsector        TEXT,
    sicindustry      TEXT,
    famasector       TEXT,
    famaindustry     TEXT,
    sector           TEXT,
    industry         TEXT,
    scalemarketcap   TEXT,
    scalerevenue     TEXT,
    relatedtickers   TEXT,
    currency         TEXT,
    location         TEXT,
    lastupdated      DATE,
    firstadded       DATE,
    firstpricedate   DATE,
    lastpricedate    DATE,
    firstquarter     DATE,
    lastquarter      DATE,
    secfilings       TEXT,
    companysite      TEXT
);
CREATE INDEX IF NOT EXISTS idx_sharadar_tickers_sector ON sharadar_tickers (sector);
CREATE INDEX IF NOT EXISTS idx_sharadar_tickers_exchange ON sharadar_tickers (exchange);

-- ─────────────────────────────────────────
-- 5. SHARADAR Actions (splits, dividends, delistings)
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sharadar_actions (
    date           DATE           NOT NULL,
    action         TEXT           NOT NULL,
    ticker         TEXT           NOT NULL,
    name           TEXT,
    value          NUMERIC(18,6),
    contraticker   TEXT,
    contraname     TEXT,
    PRIMARY KEY (date, ticker, action)
);
CREATE INDEX IF NOT EXISTS idx_sharadar_actions_ticker ON sharadar_actions (ticker, date DESC);

-- ─────────────────────────────────────────
-- 6. SHARADAR S&P 500 membership history
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sharadar_sp500 (
    date           DATE           NOT NULL,
    action         TEXT           NOT NULL,
    ticker         TEXT           NOT NULL,
    name           TEXT,
    contraticker   TEXT,
    contraname     TEXT,
    note           TEXT,
    PRIMARY KEY (date, ticker, action)
);
CREATE INDEX IF NOT EXISTS idx_sharadar_sp500_ticker ON sharadar_sp500 (ticker, date DESC);
