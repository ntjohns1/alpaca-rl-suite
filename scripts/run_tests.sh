#!/bin/bash
# Test runner script for Alpaca RL Suite
# Usage: ./scripts/run_tests.sh [test_type]
# test_type: schema | backfill | kaggle | all | quick

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo -e "${RED}pytest not found. Installing...${NC}"
    pip install pytest pytest-cov psycopg2-binary requests
fi

# Default to quick tests
TEST_TYPE=${1:-quick}

echo -e "${GREEN}=== Alpaca RL Suite Test Runner ===${NC}"
echo ""

# Function to check if service is running
check_service() {
    local service=$1
    local url=$2
    
    if curl -s -f "$url" > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} $service is running"
        return 0
    else
        echo -e "${RED}✗${NC} $service is not running"
        return 1
    fi
}

# Function to run tests
run_tests() {
    local test_file=$1
    local test_name=$2
    
    echo ""
    echo -e "${YELLOW}Running $test_name...${NC}"
    
    if pytest "$test_file" -v --tb=short; then
        echo -e "${GREEN}✓ $test_name passed${NC}"
        return 0
    else
        echo -e "${RED}✗ $test_name failed${NC}"
        return 1
    fi
}

# Check prerequisites based on test type
case $TEST_TYPE in
    schema|quick)
        echo "Checking prerequisites for schema tests..."
        if ! check_service "PostgreSQL" "http://localhost:5432"; then
            echo -e "${YELLOW}Note: PostgreSQL check failed, but might still work${NC}"
        fi
        ;;
    
    backfill)
        echo "Checking prerequisites for backfill tests..."
        check_service "PostgreSQL" "http://localhost:5432" || true
        check_service "market-ingest" "http://localhost:3003/health" || {
            echo -e "${RED}market-ingest service required. Run: docker-compose up -d market-ingest${NC}"
            exit 1
        }
        ;;
    
    kaggle)
        echo "Checking prerequisites for Kaggle tests..."
        check_service "PostgreSQL" "http://localhost:5432" || true
        check_service "kaggle-orchestrator" "http://localhost:8011/kaggle/health" || {
            echo -e "${RED}kaggle-orchestrator service required. Run: docker-compose up -d kaggle-orchestrator${NC}"
            exit 1
        }
        ;;
    
    all)
        echo "Checking prerequisites for all tests..."
        check_service "PostgreSQL" "http://localhost:5432" || true
        check_service "market-ingest" "http://localhost:3003/health" || {
            echo -e "${YELLOW}Warning: market-ingest not running. Some tests will be skipped.${NC}"
        }
        check_service "kaggle-orchestrator" "http://localhost:8011/kaggle/health" || {
            echo -e "${YELLOW}Warning: kaggle-orchestrator not running. Some tests will be skipped.${NC}"
        }
        ;;
esac

# Run tests based on type
FAILED=0

case $TEST_TYPE in
    schema)
        run_tests "tests/test_schema_validation.py" "Schema Validation Tests" || FAILED=1
        ;;
    
    backfill)
        run_tests "tests/test_backfill_e2e.py" "Backfill E2E Tests" || FAILED=1
        ;;
    
    kaggle)
        run_tests "tests/test_kaggle_integration.py" "Kaggle Integration Tests" || FAILED=1
        ;;
    
    quick)
        echo -e "${YELLOW}Running quick tests (schema validation only)...${NC}"
        run_tests "tests/test_schema_validation.py" "Schema Validation Tests" || FAILED=1
        ;;
    
    all)
        echo -e "${YELLOW}Running full test suite...${NC}"
        run_tests "tests/test_schema_validation.py" "Schema Validation Tests" || FAILED=1
        run_tests "tests/test_backfill_e2e.py" "Backfill E2E Tests" || FAILED=1
        run_tests "tests/test_kaggle_integration.py" "Kaggle Integration Tests" || FAILED=1
        ;;
    
    *)
        echo -e "${RED}Unknown test type: $TEST_TYPE${NC}"
        echo "Usage: $0 [schema|backfill|kaggle|all|quick]"
        exit 1
        ;;
esac

# Summary
echo ""
echo -e "${GREEN}=== Test Summary ===${NC}"
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed. Check output above.${NC}"
    exit 1
fi
