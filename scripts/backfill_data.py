#!/usr/bin/env python3
"""
Backfill historical market data using the market-ingest service.
Usage:
    python backfill_data.py --timeframe 1d --start 2022-01-01 --end 2024-12-31
    python backfill_data.py --timeframe 1m --start 2024-01-01 --end 2024-12-31 --symbols SPY QQQ
"""
import argparse
import requests
import time
import sys
from datetime import datetime
from typing import List

# Default symbol lists
SYMBOL_GROUPS = {
    "indices": ["SPY", "QQQ", "IWM", "DIA"],
    "tech": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA"],
    "sectors": ["XLF", "XLE", "XLK", "XLV", "XLI", "XLP", "XLU", "XLB", "XLRE", "XLC", "XLY"],
    "bonds": ["TLT", "IEF", "SHY", "LQD", "HYG"],
    "commodities": ["GLD", "SLV", "USO", "UNG"],
    "crypto": ["BTCUSD", "ETHUSD"],
}

def backfill_symbols(
    symbols: List[str],
    timeframe: str,
    start_date: str,
    end_date: str,
    base_url: str = "http://localhost:3003",
    batch_size: int = 10
) -> dict:
    """Backfill data for a list of symbols in batches"""
    
    results = {
        "total": len(symbols),
        "succeeded": 0,
        "failed": 0,
        "jobs": []
    }
    
    # Process in batches to avoid overwhelming the API
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        
        print(f"\n📊 Backfilling batch {i//batch_size + 1} ({len(batch)} symbols): {', '.join(batch)}")
        
        payload = {
            "symbols": batch,
            "timeframe": timeframe,
            "startDate": start_date,
            "endDate": end_date
        }
        
        try:
            response = requests.post(
                f"{base_url}/market/backfill",
                json=payload,
                timeout=10
            )
            
            if response.status_code == 202:
                data = response.json()
                job_id = data.get("jobId")
                print(f"✅ Job started: {job_id}")
                results["succeeded"] += len(batch)
                results["jobs"].append({
                    "jobId": job_id,
                    "symbols": batch,
                    "status": "accepted"
                })
            else:
                print(f"❌ Failed: {response.status_code} - {response.text}")
                results["failed"] += len(batch)
                
        except Exception as e:
            print(f"❌ Error: {e}")
            results["failed"] += len(batch)
        
        # Rate limiting
        if i + batch_size < len(symbols):
            time.sleep(1)
    
    return results


def check_data(symbol: str, timeframe: str, base_url: str = "http://localhost:3003"):
    """Check if data exists for a symbol"""
    try:
        response = requests.get(
            f"{base_url}/market/bars/{symbol}",
            params={"timeframe": timeframe, "limit": 10},
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            if data:
                print(f"✅ {symbol}: {len(data)} bars found (latest: {data[-1].get('time', 'N/A')})")
                return True
            else:
                print(f"⚠️  {symbol}: No data found")
                return False
        else:
            print(f"❌ {symbol}: Error {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ {symbol}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Backfill historical market data")
    parser.add_argument("--timeframe", "-t", default="1d", choices=["1m", "1d"],
                        help="Timeframe: 1m (minute) or 1d (daily)")
    parser.add_argument("--start", "-s", required=True,
                        help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", "-e", required=True,
                        help="End date (YYYY-MM-DD)")
    parser.add_argument("--symbols", "-y", nargs="+",
                        help="Specific symbols to backfill")
    parser.add_argument("--groups", "-g", nargs="+", choices=list(SYMBOL_GROUPS.keys()),
                        help="Symbol groups to backfill (indices, tech, sectors, bonds, commodities)")
    parser.add_argument("--all", "-a", action="store_true",
                        help="Backfill all symbol groups")
    parser.add_argument("--batch-size", "-b", type=int, default=10,
                        help="Number of symbols per batch")
    parser.add_argument("--url", "-u", default="http://localhost:3003",
                        help="Market ingest service URL")
    parser.add_argument("--check", "-c", action="store_true",
                        help="Check existing data instead of backfilling")
    
    args = parser.parse_args()
    
    # Validate dates
    try:
        datetime.strptime(args.start, "%Y-%m-%d")
        datetime.strptime(args.end, "%Y-%m-%d")
    except ValueError:
        print("❌ Invalid date format. Use YYYY-MM-DD")
        sys.exit(1)
    
    # Determine symbols to process
    symbols = []
    
    if args.symbols:
        symbols = args.symbols
    elif args.groups:
        for group in args.groups:
            symbols.extend(SYMBOL_GROUPS[group])
    elif args.all:
        for group_symbols in SYMBOL_GROUPS.values():
            symbols.extend(group_symbols)
    else:
        # Default: indices only
        symbols = SYMBOL_GROUPS["indices"]
    
    # Remove duplicates
    symbols = list(set(symbols))
    
    print("=" * 60)
    print("Historical Data Backfill")
    print("=" * 60)
    print(f"Timeframe:   {args.timeframe}")
    print(f"Date Range:  {args.start} to {args.end}")
    print(f"Symbols:     {len(symbols)} ({', '.join(symbols[:5])}{'...' if len(symbols) > 5 else ''})")
    print(f"Service URL: {args.url}")
    print("=" * 60)
    
    # Check mode
    if args.check:
        print("\n🔍 Checking existing data...\n")
        for symbol in symbols:
            check_data(symbol, args.timeframe, args.url)
        return
    
    # Backfill mode
    print("\n🚀 Starting backfill...\n")
    
    results = backfill_symbols(
        symbols=symbols,
        timeframe=args.timeframe,
        start_date=args.start,
        end_date=args.end,
        base_url=args.url,
        batch_size=args.batch_size
    )
    
    # Summary
    print("\n" + "=" * 60)
    print("Backfill Summary")
    print("=" * 60)
    print(f"Total symbols:    {results['total']}")
    print(f"Succeeded:        {results['succeeded']}")
    print(f"Failed:           {results['failed']}")
    print(f"Jobs created:     {len(results['jobs'])}")
    print("=" * 60)
    
    if results['succeeded'] > 0:
        print("\n✅ Backfill jobs submitted successfully!")
        print("\nMonitor progress:")
        print("  docker-compose logs -f market-ingest")
        print("\nCheck data:")
        print(f"  python {sys.argv[0]} --check --timeframe {args.timeframe} --symbols {' '.join(symbols[:3])}")
    
    if results['failed'] > 0:
        print("\n⚠️  Some jobs failed. Check the logs for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
