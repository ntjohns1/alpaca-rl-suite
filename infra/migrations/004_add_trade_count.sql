-- 004_add_trade_count.sql
-- Adds the trade_count column to bar_1d, which was present in the
-- original init.sql but missing from databases created before that
-- column was included. IF NOT EXISTS makes this idempotent.

ALTER TABLE bar_1d ADD COLUMN IF NOT EXISTS trade_count INTEGER;
