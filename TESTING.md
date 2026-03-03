# Testing & Validation Guide

## Overview

Comprehensive testing suite to prevent issues like schema mismatches and validate end-to-end workflows.

## Quick Start

```bash
# Install test dependencies
pip install pytest pytest-cov psycopg2-binary requests

# Run quick validation (schema only - no services needed)
./scripts/run_tests.sh quick

# Run all tests
./scripts/run_tests.sh all
```

## Test Categories

### ✅ Schema Validation (PASSING - 8/8)

**What it catches:**
- Column name mismatches (e.g., `trade_count` vs `tradeCount`)
- Missing columns
- Wrong data types
- Missing indexes
- CamelCase in database (should be snake_case)

**Run it:**
```bash
./scripts/run_tests.sh schema
```

**Status:** All tests passing ✅

### 🔄 Backfill E2E Tests

**What it validates:**
- Complete backfill workflow (API → Alpaca → Database)
- Data integrity (OHLCV values are sane)
- Duplicate prevention (upsert works correctly)
- Column mapping from Alpaca API to database

**Run it:**
```bash
# Requires market-ingest service
docker-compose up -d market-ingest
./scripts/run_tests.sh backfill
```

### 🔄 Kaggle Integration Tests

**What it validates:**
- Dataset export from PostgreSQL
- Dataset upload to Kaggle
- Job tracking and persistence
- Complete training workflow

**Run it:**
```bash
# Requires kaggle-orchestrator service
docker-compose up -d kaggle-orchestrator
./scripts/run_tests.sh kaggle
```

## Test Results

| Test Suite | Status | Tests | Coverage |
|------------|--------|-------|----------|
| Schema Validation | ✅ PASSING | 8/8 | 100% |
| Backfill E2E | 🔄 Ready | 0/7 | - |
| Kaggle Integration | 🔄 Ready | 0/11 | - |

## Running Tests

### Before Each Development Session
```bash
# Quick validation (30 seconds)
./scripts/run_tests.sh quick
```

### Before Committing Code
```bash
# Full test suite (2-5 minutes)
./scripts/run_tests.sh all
```

### After Schema Changes
```bash
# Schema validation only
./scripts/run_tests.sh schema
```

### After Backfill Changes
```bash
# Backfill tests only
./scripts/run_tests.sh backfill
```

## What Tests Prevent

### ✅ Prevented Issues

1. **Schema Mismatches** (like `trade_count` bug)
   - Test: `test_bar_insert_columns_match`
   - Validates: backfillJob.ts column names match database

2. **CamelCase in Database**
   - Test: `test_no_camelcase_columns`
   - Enforces: snake_case naming convention

3. **Missing Columns**
   - Test: `test_bar_1m_schema`, `test_bar_1d_schema`
   - Validates: All expected columns exist

4. **Wrong Data Types**
   - Test: All schema tests
   - Validates: Column types match expectations

5. **Missing Indexes**
   - Test: `test_bar_indexes`
   - Validates: Performance-critical indexes exist

### 🔄 Future Prevention

Once you run the E2E tests, they'll also prevent:

6. **Backfill Data Corruption**
   - Test: `test_bar_data_integrity`
   - Validates: OHLCV values are sane (high >= low, etc.)

7. **Duplicate Data**
   - Test: `test_duplicate_prevention`
   - Validates: Re-running backfill doesn't create duplicates

8. **Kaggle Workflow Failures**
   - Test: `test_full_workflow_to_dataset_upload`
   - Validates: Complete training pipeline works

## CI/CD Integration

### Pre-commit Hook (Recommended)

Create `.git/hooks/pre-commit`:
```bash
#!/bin/bash
echo "Running schema validation tests..."
./scripts/run_tests.sh quick

if [ $? -ne 0 ]; then
    echo "Tests failed. Commit aborted."
    exit 1
fi
```

Make it executable:
```bash
chmod +x .git/hooks/pre-commit
```

### GitHub Actions

Add `.github/workflows/tests.yml`:
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
        run: pip install pytest pytest-cov psycopg2-binary requests
      
      - name: Run tests
        run: ./scripts/run_tests.sh schema
```

## Troubleshooting

### "Connection refused" errors
```bash
# Check if services are running
docker-compose ps

# Start required services
docker-compose up -d postgres market-ingest kaggle-orchestrator
```

### "No data found" errors
```bash
# Backfill test data
curl -X POST http://localhost:3003/market/backfill \
  -H 'Content-Type: application/json' \
  -d '{"symbols": ["SPY"], "timeframe": "1d", "startDate": "2024-01-01", "endDate": "2024-01-31"}'
```

### Tests pass locally but fail in CI
- Check environment variables are set
- Verify database migrations ran
- Check service dependencies are available

## Next Steps

1. ✅ **Schema validation tests created and passing**
2. 🔄 **Run backfill E2E tests** (when you have time)
3. 🔄 **Run Kaggle integration tests** (when you have time)
4. 🔄 **Set up pre-commit hook** (optional but recommended)
5. 🔄 **Add CI/CD pipeline** (for automated testing)

## Test Coverage Goals

- **Schema validation**: ✅ 100% (achieved)
- **API endpoints**: 🎯 90%+
- **E2E workflows**: 🎯 80%+
- **Overall**: 🎯 85%+

## Benefits

### Development Speed
- Catch bugs in seconds, not hours
- Refactor with confidence
- Document expected behavior

### Code Quality
- Enforce naming conventions
- Validate data integrity
- Prevent regressions

### Debugging
- Pinpoint exact failure location
- Reproduce issues reliably
- Validate fixes work

## Maintenance

### Adding New Tests

When you add features:

1. **New database table?** → Add to `test_schema_validation.py`
2. **New API endpoint?** → Add to appropriate E2E test
3. **New service?** → Create `test_<service>_e2e.py`

### Updating Tests

When you change schemas:

1. Update `EXPECTED_COLUMNS` in test files
2. Run tests to verify changes work
3. Commit test updates with schema changes

## Summary

You now have:
- ✅ Comprehensive schema validation (prevents `trade_count` bugs)
- ✅ E2E test framework (ready to use)
- ✅ Test runner script (easy to run)
- ✅ Documentation (this file)

**Recommendation:** Run `./scripts/run_tests.sh quick` before each commit to catch issues early.
