#!/usr/bin/env python3
"""
Export multi-asset 1-minute training dataset from PostgreSQL to CSV for Kaggle upload.
Usage: python export_multiasset_1m.py --symbols SPY QQQ IWM --start 2024-01-01 --end 2024-12-31 --output-dir kaggle/datasets/multi-asset-1m
"""
import argparse
import os
import json
import psycopg2
import pandas as pd
from pathlib import Path


def export_symbol_1m(symbol: str, start_date: str, end_date: str, output_path: str, database_url: str):
    """Export 1-minute bar data for a single symbol"""
    print(f"\n📊 Exporting {symbol} 1-minute data...")
    
    conn = psycopg2.connect(database_url)
    
    # Query 1-minute data
    df = pd.read_sql(
        """SELECT time, open::float, high::float, low::float, 
                  close::float, volume::bigint, vwap::float, trade_count::int
           FROM bar_1m 
           WHERE symbol=%s AND time >= %s::date AND time < (%s::date + INTERVAL '1 day')
           ORDER BY time""",
        conn, params=(symbol, start_date, end_date),
    )
    conn.close()
    
    if len(df) == 0:
        raise ValueError(f"No data found for {symbol} between {start_date} and {end_date}")
    
    # Save to CSV
    df.to_csv(output_path, index=False)
    
    print(f"  ✓ Exported {len(df):,} bars")
    print(f"  ✓ Time range: {df['time'].min()} to {df['time'].max()}")
    print(f"  ✓ File size: {os.path.getsize(output_path) / (1024*1024):.2f} MB")
    
    return {
        'bars': len(df),
        'start': str(df['time'].min()),
        'end': str(df['time'].max()),
        'size_mb': os.path.getsize(output_path) / (1024*1024)
    }


def create_dataset_metadata(output_dir: str, symbols: list, stats: dict, start_date: str, end_date: str):
    """Create Kaggle dataset metadata JSON"""
    
    metadata = {
        "title": "Multi-Asset Indices 1-Minute Data (SPY, QQQ, IWM)",
        "id": "nelsonjohns/multi-asset-indices-1m",
        "licenses": [{"name": "CC0-1.0"}],
        "keywords": [
            "finance",
            "trading",
            "reinforcement learning",
            "high frequency",
            "etf",
            "indices",
            "intraday"
        ],
        "description": f"1-minute OHLCV data for major US equity indices: SPY (S&P 500), QQQ (Nasdaq-100), IWM (Russell 2000). Data covers {start_date} to {end_date}. Includes time, open, high, low, close, volume, vwap, and trade_count. Suitable for high-frequency reinforcement learning training with consistent time ranges across all assets.",
        "resources": []
    }
    
    # Add resource for each symbol
    for symbol in symbols:
        bar_count = stats[symbol]['bars']
        time_range = stats[symbol]['start'][:10] + " to " + stats[symbol]['end'][:10]
        size_mb = stats[symbol]['size_mb']
        metadata["resources"].append({
            "path": f"{symbol}_bar_1m.csv",
            "description": f"{symbol} 1-minute bars - {bar_count:,} bars from {time_range} ({size_mb:.1f} MB)"
        })
    
    # Save metadata
    metadata_path = os.path.join(output_dir, "dataset-metadata.json")
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    print(f"\n✓ Created metadata: {metadata_path}")
    return metadata_path


def main():
    parser = argparse.ArgumentParser(description="Export multi-asset 1-minute data for Kaggle")
    parser.add_argument("--symbols", nargs="+", default=["SPY", "QQQ", "IWM"],
                        help="Symbols to export (default: SPY QQQ IWM)")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--output-dir", default="kaggle/datasets/multi-asset-1m",
                        help="Output directory for dataset")
    parser.add_argument("--database-url", 
                        default=os.getenv("DATABASE_URL", "postgresql://rl_user:rl_pass@localhost:5432/alpaca_rl"),
                        help="PostgreSQL connection string")
    
    args = parser.parse_args()
    
    try:
        # Create output directory
        output_dir = args.output_dir
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        print(f"🚀 Exporting multi-asset 1-minute dataset")
        print(f"   Symbols: {', '.join(args.symbols)}")
        print(f"   Period: {args.start} to {args.end}")
        print(f"   Output: {output_dir}")
        
        # Export each symbol
        stats = {}
        for symbol in args.symbols:
            output_path = os.path.join(output_dir, f"{symbol}_bar_1m.csv")
            stats[symbol] = export_symbol_1m(
                symbol, args.start, args.end, output_path, args.database_url
            )
        
        # Create metadata
        create_dataset_metadata(output_dir, args.symbols, stats, args.start, args.end)
        
        # Summary
        total_bars = sum(s['bars'] for s in stats.values())
        total_size = sum(s['size_mb'] for s in stats.values())
        
        print("\n" + "="*60)
        print("✅ EXPORT COMPLETE")
        print("="*60)
        print(f"Total bars: {total_bars:,}")
        print(f"Total size: {total_size:.2f} MB")
        print(f"Output directory: {output_dir}")
        
        print("\n📤 Next steps:")
        print(f"1. Review files in {output_dir}/")
        print(f"2. Upload to Kaggle:")
        print(f"   cd {output_dir}")
        print(f"   kaggle datasets create -p .")
        print(f"   (or 'kaggle datasets version -p . -m \"Updated data\"' to update existing)")
        print(f"3. Attach dataset to your training notebook")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
