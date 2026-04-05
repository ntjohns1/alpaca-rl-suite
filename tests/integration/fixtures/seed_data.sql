DELETE FROM feature_row WHERE symbol IN ('SPY', 'QQQ');
DELETE FROM sharadar_daily WHERE ticker IN ('SPY', 'QQQ');
DELETE FROM sharadar_sf1 WHERE ticker IN ('SPY', 'QQQ');
DELETE FROM dataset_manifest WHERE name LIKE 'integration-%';
DELETE FROM bar_1d WHERE symbol IN ('SPY', 'QQQ');

INSERT INTO bar_1d (
    time, symbol, open, high, low, close, volume, vwap, trade_count, source, closeadj, closeunadj
)
SELECT
    (DATE '2024-01-01' + (i * INTERVAL '1 day'))::timestamptz,
    sym.symbol,
    100 + i,
    101 + i,
    99 + i,
    100.5 + i,
    1000000 + (i * 1000),
    100.25 + i,
    100 + i,
    'integration',
    100.5 + i,
    100.5 + i
FROM generate_series(0, 119) AS gs(i)
CROSS JOIN (VALUES ('SPY'), ('QQQ')) AS sym(symbol)
ON CONFLICT (time, symbol) DO UPDATE SET
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    vwap = EXCLUDED.vwap,
    trade_count = EXCLUDED.trade_count,
    source = EXCLUDED.source,
    closeadj = EXCLUDED.closeadj,
    closeunadj = EXCLUDED.closeunadj;

INSERT INTO sharadar_daily (
    ticker, date, lastupdated, ev, evebit, evebitda, marketcap, pb, pe, ps
)
SELECT
    sym.symbol,
    (DATE '2024-01-01' + (i * INTERVAL '1 day'))::date,
    (DATE '2024-01-01' + (i * INTERVAL '1 day'))::date,
    1000000000 + (i * 1000000),
    12.5 + (i * 0.01),
    14.0 + (i * 0.01),
    50000000000 + (i * 10000000),
    4.0 + (i * 0.01),
    22.0 + (i * 0.02),
    5.0 + (i * 0.01)
FROM generate_series(0, 119) AS gs(i)
CROSS JOIN (VALUES ('SPY'), ('QQQ')) AS sym(symbol)
ON CONFLICT (date, ticker) DO UPDATE SET
    lastupdated = EXCLUDED.lastupdated,
    ev = EXCLUDED.ev,
    evebit = EXCLUDED.evebit,
    evebitda = EXCLUDED.evebitda,
    marketcap = EXCLUDED.marketcap,
    pb = EXCLUDED.pb,
    pe = EXCLUDED.pe,
    ps = EXCLUDED.ps;

INSERT INTO sharadar_sf1 (
    ticker, dimension, calendardate, datekey, reportperiod, fiscalperiod, lastupdated,
    revenue, debt, equity, marketcap, roe, roa, fcf, extras
)
VALUES
    ('SPY', 'ARQ', '2023-12-31', '2024-01-31', '2023-12-31', 'Q4', '2024-01-31', 1000000000, 200000000, 500000000, 50000000000, 0.18, 0.09, 120000000, '{}'::jsonb),
    ('SPY', 'ARQ', '2024-03-31', '2024-04-30', '2024-03-31', 'Q1', '2024-04-30', 1100000000, 205000000, 520000000, 51000000000, 0.19, 0.095, 125000000, '{}'::jsonb),
    ('QQQ', 'ARQ', '2023-12-31', '2024-01-31', '2023-12-31', 'Q4', '2024-01-31', 1500000000, 300000000, 700000000, 70000000000, 0.16, 0.08, 150000000, '{}'::jsonb),
    ('QQQ', 'ARQ', '2024-03-31', '2024-04-30', '2024-03-31', 'Q1', '2024-04-30', 1650000000, 305000000, 725000000, 71000000000, 0.17, 0.082, 158000000, '{}'::jsonb)
ON CONFLICT (calendardate, ticker, dimension) DO UPDATE SET
    datekey = EXCLUDED.datekey,
    reportperiod = EXCLUDED.reportperiod,
    fiscalperiod = EXCLUDED.fiscalperiod,
    lastupdated = EXCLUDED.lastupdated,
    revenue = EXCLUDED.revenue,
    debt = EXCLUDED.debt,
    equity = EXCLUDED.equity,
    marketcap = EXCLUDED.marketcap,
    roe = EXCLUDED.roe,
    roa = EXCLUDED.roa,
    fcf = EXCLUDED.fcf,
    extras = EXCLUDED.extras;
