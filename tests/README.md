# Testing Strategy

This directory contains comprehensive tests to validate the Alpaca RL Suite end-to-end.

## Test Categories

### 1. Schema Validation Tests (`test_schema_validation.py`)

**Purpose**: Catch schema mismatches between database and application code.

**What it tests**:
- ✅ Database column names match code expectations (e.g., `trade_count` not `tradeCount`)
- ✅ Column data types are correct
- ✅ Required indexes exist
- ✅ TimescaleDB hypertables are configured
- ✅ No camelCase columns in database (enforce snake_case)

**Why it matters**: Prevents runtime errors like the `trade_count` issue you encountered.

**Run it**:
```bash
pytest tests/test_schema_validation.py -v
```

### 2. Backfill E2E Tests (`test_backfill_e2e.py`)

**Purpose**: Validate complete backfill workflow from API to database.

**What it tests**:
- ✅ API endpoint validation
- ✅ Data fetching from Alpaca
- ✅ Database insertion
- ✅ Data integrity (OHLCV values are sane)
- ✅ Duplicate prevention (upsert works)
- ✅ Column mapping (Alpaca API → database)

**Why it matters**: Ensures your market data pipeline works correctly.

**Run it**:
```bash
# Requires market-ingest service running
docker-compose up -d market-ingest
pytest tests/test_backfill_e2e.py -v
```

### 3. Kaggle Integration Tests (`test_kaggle_integration.py`)

**Purpose**: Validate Kaggle orchestrator and training workflow.

**What it tests**:
- ✅ Kaggle orchestrator API
- ✅ Job creation and tracking
- ✅ Dataset export from PostgreSQL
- ✅ Dataset upload to Kaggle
- ✅ Job persistence to database
- ✅ Complete workflow (create → export → upload)

**Why it matters**: Ensures your training pipeline works end-to-end.

**Run it**:
```bash
# Requires kaggle-orchestrator service running and credentials configured
docker-compose up -d kaggle-orchestrator
pytest tests/test_kaggle_integration.py -v
```

## Running All Tests

### Quick Test (Schema Only)
```bash
# Fast - no external dependencies
pytest tests/test_schema_validation.py -v
```

### Full Test Suite
```bash
# Start all services
cd infra
docker-compose up -d

# Run all tests
cd ..
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=services --cov-report=html
```

### Continuous Integration
```bash
# Run tests that don't require external services
pytest tests/test_schema_validation.py -v -m "not slow"

# Run all tests including slow E2E tests
pytest tests/ -v
```

## Test Markers

Tests are marked for selective execution:

- `@pytest.mark.slow` - Tests that take >10 seconds
- `@pytest.mark.integration` - Tests requiring external services
- `@pytest.mark.e2e` - Full end-to-end workflow tests

**Run only fast tests**:
```bash
pytest tests/ -v -m "not slow"
```

**Run only integration tests**:
```bash
pytest tests/ -v -m integration
```

## Prerequisites

### For Schema Tests
- PostgreSQL running with migrations applied
- No other dependencies

### For Backfill Tests
- PostgreSQL running
- market-ingest service running
- Alpaca API credentials configured

### For Kaggle Tests
- PostgreSQL running
- kaggle-orchestrator service running
- Kaggle API credentials configured
- At least some market data in database (for export tests)

## Setting Up Test Environment

### 1. Install Test Dependencies
```bash
pip install pytest pytest-cov psycopg2-binary requests
```

### 2. Configure Environment
```bash
# Copy .env.example to .env and set:
DATABASE_URL=postgresql://rl_user:rl_pass@localhost:5432/alpaca_rl
MARKET_INGEST_URL=http://localhost:3003
KAGGLE_ORCHESTRATOR_URL=http://localhost:8011
ALPACA_API_KEY=your_key
ALPACA_API_SECRET=your_secret
KAGGLE_API_TOKEN=your_token
KAGGLE_USERNAME=your_username
```

### 3. Start Services
```bash
cd infra
docker-compose up -d postgres market-ingest kaggle-orchestrator
```

### 4. Run Migrations
```bash
docker-compose exec postgres psql -U rl_user -d alpaca_rl -f /docker-entrypoint-initdb.d/init.sql
```

### 5. Backfill Test Data (Optional)
```bash
curl -X POST http://localhost:3003/market/backfill \
  -H 'Content-Type: application/json' \
  -d '{
    "symbols": ["SPY"],
    "timeframe": "1d",
    "startDate": "2024-01-01",
    "endDate": "2024-01-31"
  }'
```

## Test Data Cleanup

Tests automatically clean up after themselves, but you can manually clean:

```bash
# Clean test data from database
docker-compose exec postgres psql -U rl_user -d alpaca_rl -c \
  "DELETE FROM bar_1d WHERE symbol = 'TEST';"

# Clean test Kaggle jobs
docker-compose exec postgres psql -U rl_user -d alpaca_rl -c \
  "DELETE FROM kaggle_training_job WHERE name LIKE '%test%';"
```

## Common Issues

### "Connection refused" errors
```bash
# Ensure services are running
docker-compose ps

# Check logs
docker-compose logs market-ingest
docker-compose logs kaggle-orchestrator
```

### "No data found" errors
```bash
# Backfill some test data first
curl -X POST http://localhost:3003/market/backfill \
  -H 'Content-Type: application/json' \
  -d '{"symbols": ["SPY"], "timeframe": "1d", "startDate": "2024-01-01", "endDate": "2024-01-31"}'
```

### "Kaggle credentials not configured"
```bash
# Check .env file
grep KAGGLE .env

# Should see:
# KAGGLE_API_TOKEN=...
# KAGGLE_USERNAME=...
```

## Adding New Tests

When adding features, add corresponding tests:

1. **Schema changes**: Update `test_schema_validation.py`
2. **New API endpoints**: Add to appropriate E2E test file
3. **New services**: Create new test file `test_<service>_e2e.py`

### Test Template
```python
import pytest
import requests

class TestNewFeature:
    """Test description"""
    
    def test_basic_functionality(self):
        """Test basic case"""
        # Arrange
        # Act
        # Assert
        pass
    
    def test_error_handling(self):
        """Test error cases"""
        pass
    
    @pytest.mark.slow
    def test_e2e_workflow(self):
        """Test complete workflow"""
        pass
```

## CI/CD Integration

### GitHub Actions Example
```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: timescale/timescaledb:latest-pg15
        env:
          POSTGRES_USER: rl_user
          POSTGRES_PASSWORD: rl_pass
          POSTGRES_DB: alpaca_rl
        ports:
          - 5432:5432
    
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install pytest pytest-cov psycopg2-binary requests
      
      - name: Run schema tests
        run: pytest tests/test_schema_validation.py -v
      
      - name: Run E2E tests
        run: pytest tests/ -v -m "not slow"
        env:
          DATABASE_URL: postgresql://rl_user:rl_pass@localhost:5432/alpaca_rl
```

## Test Coverage Goals

- **Schema validation**: 100% (all tables and columns)
- **API endpoints**: 90%+ (all happy paths + major error cases)
- **E2E workflows**: 80%+ (critical user journeys)
- **Overall**: 85%+

## Next Steps

1. ✅ Run schema validation tests
2. ✅ Run backfill E2E tests
3. ✅ Run Kaggle integration tests
4. 🔄 Add tests for rl-train service
5. 🔄 Add tests for rl-infer service
6. 🔄 Set up CI/CD pipeline
7. 🔄 Add performance/load tests
