#!/usr/bin/env python3
"""
⚠️  DEPRECATED — Use the unified CLI or Dataset Builder service instead.

    CLI:  alpaca-rl dataset export --symbol SPY --format csv --output spy.csv
    API:  POST http://localhost:8003/datasets/export?symbols=SPY&format=csv

The dataset-builder service now handles CSV and Parquet exports with date
filtering. The kaggle-orchestrator also exports datasets automatically as
part of the training workflow. This script is kept for reference only.
─────────────────────────────────────────────────────────────────────────

Export training dataset from PostgreSQL to CSV for Kaggle upload.
Usage: python export_dataset.py --symbol SPY --output spy_data.csv
"""
import argparse
import os
import psycopg2
import pandas as pd
from datetime import datetime


def export_dataset(symbol: str, output_path: str, database_url: str = None):
    """Export bar data from PostgreSQL to CSV"""
    if database_url is None:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise ValueError("DATABASE_URL environment variable not set")
    
    print(f"Connecting to database...")
    conn = psycopg2.connect(database_url)
    
    print(f"Exporting data for {symbol}...")
    df = pd.read_sql(
        """SELECT time::date as date, open::float, high::float,
                  low::float, close::float, volume::bigint
           FROM bar_1d WHERE symbol=%s ORDER BY time""",
        conn, params=(symbol,),
    )
    conn.close()
    
    if len(df) < 200:
        raise ValueError(f"Insufficient data for {symbol}: {len(df)} bars (need at least 200)")
    
    # Save to CSV
    df.to_csv(output_path, index=False)
    
    print(f"✓ Exported {len(df)} bars for {symbol}")
    print(f"  Date range: {df['date'].min()} to {df['date'].max()}")
    print(f"  Output: {output_path}")
    print(f"  File size: {os.path.getsize(output_path) / 1024:.1f} KB")
    
    return df


def main():
    parser = argparse.ArgumentParser(description="Export trading data for Kaggle")
    parser.add_argument("--symbol", required=True, help="Stock symbol (e.g., SPY)")
    parser.add_argument("--output", required=True, help="Output CSV file path")
    parser.add_argument("--database-url", help="PostgreSQL connection string (or use DATABASE_URL env var)")
    
    args = parser.parse_args()
    
    try:
        export_dataset(args.symbol, args.output, args.database_url)
        print("\n✓ Dataset ready for Kaggle upload!")
        print(f"\nNext steps:")
        print(f"1. Upload {args.output} to Kaggle as a dataset")
        print(f"2. Attach the dataset to your training notebook")
        print(f"3. Run the notebook with GPU enabled")
    except Exception as e:
        print(f"✗ Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
