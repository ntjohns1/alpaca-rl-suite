-- 003_feature_row_sharadar.sql
-- Add SHARADAR-derived valuation and fundamental feature columns to feature_row.
-- All new columns are nullable DOUBLE PRECISION — backward compatible.

ALTER TABLE feature_row ADD COLUMN IF NOT EXISTS pe             DOUBLE PRECISION;
ALTER TABLE feature_row ADD COLUMN IF NOT EXISTS pb             DOUBLE PRECISION;
ALTER TABLE feature_row ADD COLUMN IF NOT EXISTS ps             DOUBLE PRECISION;
ALTER TABLE feature_row ADD COLUMN IF NOT EXISTS evebitda       DOUBLE PRECISION;
ALTER TABLE feature_row ADD COLUMN IF NOT EXISTS marketcap_log  DOUBLE PRECISION;
ALTER TABLE feature_row ADD COLUMN IF NOT EXISTS roe            DOUBLE PRECISION;
ALTER TABLE feature_row ADD COLUMN IF NOT EXISTS roa            DOUBLE PRECISION;
ALTER TABLE feature_row ADD COLUMN IF NOT EXISTS debt_equity    DOUBLE PRECISION;
ALTER TABLE feature_row ADD COLUMN IF NOT EXISTS revenue_growth DOUBLE PRECISION;
ALTER TABLE feature_row ADD COLUMN IF NOT EXISTS fcf_yield      DOUBLE PRECISION;
