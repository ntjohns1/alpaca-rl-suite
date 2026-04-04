#!/usr/bin/env python3
"""
⚠️  DEPRECATED — Use the unified CLI or Dataset Builder service instead.

    CLI:  alpaca-rl dataset export --symbol SPY --start 2022-01-01 --end 2024-12-31 --format csv --output spy.csv
    API:  POST http://localhost:8003/datasets/export?symbols=SPY&format=csv&start_date=2022-01-01&end_date=2024-12-31

The dataset-builder service now handles CSV and Parquet exports with date
filtering. This script is kept for reference only.
─────────────────────────────────────────────────────────────────────────

Export training dataset from PostgreSQL to CSV with date filtering.
Usage: python export_dataset_filtered.py --symbol SPY --start 2022-01-01 --end 2024-12-31 --output spy_data.csv
"""
import argparse
import os
import psycopg2
import pandas as pd


def export_dataset(symbol: str, start_date: str, end_date: str, output_path: str, database_url: str = None):
    """Export bar data from PostgreSQL to CSV with date filtering"""
    if database_url is None:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise ValueError("DATABASE_URL environment variable not set")
    
    print(f"Connecting to database...")
    conn = psycopg2.connect(database_url)
    
    print(f"Exporting data for {symbol} ({start_date} to {end_date})...")
    df = pd.read_sql(
        """SELECT time::date as date, open::float, high::float,
                  low::float, close::float, volume::bigint
           FROM bar_1d 
           WHERE symbol=%s AND time::date >= %s AND time::date <= %s
           ORDER BY time""",
        conn, params=(symbol, start_date, end_date),
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
    parser = argparse.ArgumentParser(description="Export trading data for Kaggle with date filtering")
    parser.add_argument("--symbol", required=True, help="Stock symbol (e.g., SPY)")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--output", required=True, help="Output CSV file path")
    parser.add_argument("--database-url", help="PostgreSQL connection string (or use DATABASE_URL env var)")
    
    args = parser.parse_args()
    export_dataset(args.symbol, args.start, args.end, args.output, args.database_url)


if __name__ == "__main__":
    main()
