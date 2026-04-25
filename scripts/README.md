# Scripts

Standalone Python scripts for data management.

> **Note:** Backtesting and model promotion are now handled by the
> `services/backtest` API and the unified CLI — not by scripts in this
> directory.

## backfill_data.py

Backfill historical market data from Alpaca API.

### Usage

```bash
# Backfill daily data for indices
python scripts/backfill_data.py \
  --timeframe 1d \
  --start 2020-01-01 \
  --end 2024-12-31 \
  --groups indices

# Backfill specific symbols
python scripts/backfill_data.py \
  --timeframe 1d \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --symbols SPY QQQ IWM
```

See script help for more options:
```bash
python scripts/backfill_data.py --help
```

## Environment Variables

Scripts use these environment variables:

- `DATABASE_URL` - PostgreSQL connection string (required)
- `MARKET_INGEST_URL` - Market ingest service URL (for backfill_data.py)

Example:
```bash
export DATABASE_URL="postgresql://rl_user:rl_pass@localhost:5432/alpaca_rl"
export MARKET_INGEST_URL="http://localhost:3003"
```
