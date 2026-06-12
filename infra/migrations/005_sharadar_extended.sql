-- ─────────────────────────────────────────────────────────────────────────────
-- SHARADAR Extended Datasets
-- Migration 005: Events, Indicators, Metrics, SF2 (insiders), SF3/SF3A/SF3B
--                (institutional holdings)
-- ─────────────────────────────────────────────────────────────────────────────

-- 1. Corporate Events
CREATE TABLE IF NOT EXISTS sharadar_events (
    date        DATE NOT NULL,
    ticker      TEXT NOT NULL,
    eventcodes  TEXT,
    PRIMARY KEY (date, ticker)
);
CREATE INDEX IF NOT EXISTS idx_sharadar_events_ticker ON sharadar_events (ticker, date DESC);

-- 2. Dataset Indicators (reference / metadata — not time-series)
CREATE TABLE IF NOT EXISTS sharadar_indicators (
    "table"       TEXT NOT NULL,
    indicator     TEXT NOT NULL,
    isfilter      TEXT,
    isprimarykey  TEXT,
    title         TEXT,
    description   TEXT,
    unittype      TEXT,
    PRIMARY KEY ("table", indicator)
);

-- 3. Price & Volume Metrics (supplemental daily metrics)
CREATE TABLE IF NOT EXISTS sharadar_metrics (
    date                  DATE NOT NULL,
    ticker                TEXT NOT NULL,
    lastupdated           DATE,
    beta1y                DOUBLE PRECISION,
    beta5y                DOUBLE PRECISION,
    dividendyieldforward  DOUBLE PRECISION,
    dividendyieldtrailing DOUBLE PRECISION,
    high52w               DOUBLE PRECISION,
    high5y                DOUBLE PRECISION,
    low52w                DOUBLE PRECISION,
    low5y                 DOUBLE PRECISION,
    ma200d                DOUBLE PRECISION,
    ma200w                DOUBLE PRECISION,
    ma50d                 DOUBLE PRECISION,
    ma50w                 DOUBLE PRECISION,
    price                 DOUBLE PRECISION,
    return1y              DOUBLE PRECISION,
    return5y              DOUBLE PRECISION,
    returnytd             DOUBLE PRECISION,
    volume                BIGINT,
    volumeavg1m           BIGINT,
    volumeavg3m           BIGINT,
    PRIMARY KEY (date, ticker)
);
CREATE INDEX IF NOT EXISTS idx_sharadar_metrics_ticker ON sharadar_metrics (ticker, date DESC);

-- 4. Insider Transactions (Form 4 filings — SF2)
--    filingdate / transactiondate / dateexercisable may be NULL → not a hypertable
CREATE TABLE IF NOT EXISTS sharadar_sf2 (
    ticker                            TEXT,
    filingdate                        DATE,
    formtype                          TEXT,
    issuername                        TEXT,
    ownername                         TEXT,
    officertitle                      TEXT,
    isdirector                        TEXT,
    isofficer                         TEXT,
    istenpercentowner                 TEXT,
    transactiondate                   DATE,
    securityadcode                    TEXT,
    transactioncode                   TEXT,
    sharesownedbeforetransaction      DOUBLE PRECISION,
    transactionshares                 DOUBLE PRECISION,
    sharesownedfollowingtransaction   DOUBLE PRECISION,
    transactionpricepershare          DOUBLE PRECISION,
    transactionvalue                  DOUBLE PRECISION,
    securitytitle                     TEXT,
    directorindirect                  TEXT,
    natureofownership                 TEXT,
    dateexercisable                   DATE,
    priceexercisable                  DOUBLE PRECISION,
    expirationdate                    DATE,
    rownum                            INTEGER
);
CREATE INDEX IF NOT EXISTS idx_sharadar_sf2_ticker      ON sharadar_sf2 (ticker, filingdate DESC);
CREATE INDEX IF NOT EXISTS idx_sharadar_sf2_filingdate  ON sharadar_sf2 (filingdate DESC);
CREATE INDEX IF NOT EXISTS idx_sharadar_sf2_ownername   ON sharadar_sf2 (ownername);

-- 5. Institutional Holdings — position level (SF3)
--    ~46M rows → hypertable on calendardate
CREATE TABLE IF NOT EXISTS sharadar_sf3 (
    calendardate  DATE NOT NULL,
    ticker        TEXT NOT NULL,
    investorname  TEXT NOT NULL,
    securitytype  TEXT NOT NULL,
    value         DOUBLE PRECISION,
    units         DOUBLE PRECISION,
    price         DOUBLE PRECISION,
    PRIMARY KEY (calendardate, ticker, investorname, securitytype)
);
SELECT create_hypertable('sharadar_sf3', 'calendardate', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_sharadar_sf3_ticker   ON sharadar_sf3 (ticker, calendardate DESC);
CREATE INDEX IF NOT EXISTS idx_sharadar_sf3_investor ON sharadar_sf3 (investorname, calendardate DESC);

-- 6. Institutional Holdings — security aggregate (SF3A)
--    Per-ticker summary: # holders, units held, value held, by security type
CREATE TABLE IF NOT EXISTS sharadar_sf3a (
    calendardate   DATE NOT NULL,
    ticker         TEXT NOT NULL,
    name           TEXT,
    shrholders     INTEGER,
    cllholders     INTEGER,
    putholders     INTEGER,
    wntholders     INTEGER,
    dbtholders     INTEGER,
    prfholders     INTEGER,
    fndholders     INTEGER,
    undholders     INTEGER,
    shrunits       DOUBLE PRECISION,
    cllunits       DOUBLE PRECISION,
    putunits       DOUBLE PRECISION,
    wntunits       DOUBLE PRECISION,
    dbtunits       DOUBLE PRECISION,
    prfunits       DOUBLE PRECISION,
    fndunits       DOUBLE PRECISION,
    undunits       DOUBLE PRECISION,
    shrvalue       DOUBLE PRECISION,
    cllvalue       DOUBLE PRECISION,
    putvalue       DOUBLE PRECISION,
    wntvalue       DOUBLE PRECISION,
    dbtvalue       DOUBLE PRECISION,
    prfvalue       DOUBLE PRECISION,
    fndvalue       DOUBLE PRECISION,
    undvalue       DOUBLE PRECISION,
    totalvalue     DOUBLE PRECISION,
    percentoftotal DOUBLE PRECISION,
    PRIMARY KEY (calendardate, ticker)
);
CREATE INDEX IF NOT EXISTS idx_sharadar_sf3a_ticker ON sharadar_sf3a (ticker, calendardate DESC);

-- 7. Institutional Holdings — investor aggregate (SF3B)
--    Per-investor summary: # holdings, units, value, by security type
CREATE TABLE IF NOT EXISTS sharadar_sf3b (
    calendardate   DATE NOT NULL,
    investorname   TEXT NOT NULL,
    shrholdings    INTEGER,
    cllholdings    INTEGER,
    putholdings    INTEGER,
    wntholdings    INTEGER,
    dbtholdings    INTEGER,
    prfholdings    INTEGER,
    fndholdings    INTEGER,
    undholdings    INTEGER,
    shrunits       DOUBLE PRECISION,
    cllunits       DOUBLE PRECISION,
    putunits       DOUBLE PRECISION,
    wntunits       DOUBLE PRECISION,
    dbtunits       DOUBLE PRECISION,
    prfunits       DOUBLE PRECISION,
    fndunits       DOUBLE PRECISION,
    undunits       DOUBLE PRECISION,
    shrvalue       DOUBLE PRECISION,
    cllvalue       DOUBLE PRECISION,
    putvalue       DOUBLE PRECISION,
    wntvalue       DOUBLE PRECISION,
    dbtvalue       DOUBLE PRECISION,
    prfvalue       DOUBLE PRECISION,
    fndvalue       DOUBLE PRECISION,
    undvalue       DOUBLE PRECISION,
    totalvalue     DOUBLE PRECISION,
    percentoftotal DOUBLE PRECISION,
    PRIMARY KEY (calendardate, investorname)
);
CREATE INDEX IF NOT EXISTS idx_sharadar_sf3b_investor ON sharadar_sf3b (investorname, calendardate DESC);
