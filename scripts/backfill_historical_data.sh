#!/bin/bash
# Backfill historical market data using the market-ingest service
# Usage: ./backfill_historical_data.sh [timeframe] [start_date] [end_date]

set -e

MARKET_INGEST_URL="${MARKET_INGEST_URL:-http://localhost:3003}"
TIMEFRAME="${1:-1d}"
START_DATE="${2:-2022-01-01}"
END_DATE="${3:-2024-12-31}"

# Define symbol lists
MAJOR_INDICES=("SPY" "QQQ" "IWM" "DIA")
TECH_GIANTS=("AAPL" "MSFT" "GOOGL" "AMZN" "META" "NVDA" "TSLA")
SECTOR_ETFS=("XLF" "XLE" "XLK" "XLV" "XLI" "XLP" "XLU" "XLB" "XLRE" "XLC" "XLY")
BONDS=("TLT" "IEF" "SHY" "LQD" "HYG")
COMMODITIES=("GLD" "SLV" "USO" "UNG")

echo "==================================="
echo "Historical Data Backfill Script"
echo "==================================="
echo "Timeframe: $TIMEFRAME"
echo "Date Range: $START_DATE to $END_DATE"
echo "Target: $MARKET_INGEST_URL"
echo ""

# Function to backfill a batch of symbols
backfill_batch() {
    local batch_name=$1
    shift
    local symbols=("$@")
    
    echo "📊 Backfilling $batch_name (${#symbols[@]} symbols)..."
    
    # Convert array to JSON array
    local symbols_json=$(printf '%s\n' "${symbols[@]}" | jq -R . | jq -s .)
    
    local response=$(curl -s -X POST "$MARKET_INGEST_URL/market/backfill" \
        -H "Content-Type: application/json" \
        -d "{
            \"symbols\": $symbols_json,
            \"timeframe\": \"$TIMEFRAME\",
            \"startDate\": \"$START_DATE\",
            \"endDate\": \"$END_DATE\"
        }")
    
    local job_id=$(echo "$response" | jq -r '.jobId')
    local status=$(echo "$response" | jq -r '.status')
    
    if [ "$status" = "accepted" ]; then
        echo "✅ Job started: $job_id"
        echo "   Symbols: ${symbols[*]}"
    else
        echo "❌ Failed to start job for $batch_name"
        echo "   Response: $response"
        return 1
    fi
    
    # Wait a bit between batches to avoid rate limits
    sleep 2
}

# Backfill in batches
echo "Starting backfill jobs..."
echo ""

backfill_batch "Major Indices" "${MAJOR_INDICES[@]}"
backfill_batch "Tech Giants" "${TECH_GIANTS[@]}"
backfill_batch "Sector ETFs" "${SECTOR_ETFS[@]}"
backfill_batch "Bonds" "${BONDS[@]}"
backfill_batch "Commodities" "${COMMODITIES[@]}"

echo ""
echo "==================================="
echo "✅ All backfill jobs submitted!"
echo "==================================="
echo ""
echo "Monitor progress with:"
echo "  docker-compose logs -f market-ingest"
echo ""
echo "Query data with:"
echo "  curl '$MARKET_INGEST_URL/market/bars/SPY?timeframe=$TIMEFRAME&limit=10'"
echo ""
echo "Check symbols in database:"
echo "  curl '$MARKET_INGEST_URL/market/symbols'"
