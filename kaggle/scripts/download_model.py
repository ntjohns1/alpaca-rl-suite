#!/usr/bin/env python3
"""
Download trained model from Kaggle notebook output and upload to MinIO.
Usage: python download_model.py --kernel-slug alpaca-rl-training --run-id 20260301-123456
"""
import argparse
import os
import subprocess
import boto3
from pathlib import Path


def download_from_kaggle(username: str, kernel_slug: str, output_dir: str):
    """Download kernel output using Kaggle CLI"""
    print(f"Downloading output from {username}/{kernel_slug}...")
    
    # Create output directory
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # Download using Kaggle CLI
    result = subprocess.run(
        ["kaggle", "kernels", "output", f"{username}/{kernel_slug}", "-p", output_dir],
        capture_output=True, text=True
    )
    
    if result.returncode != 0:
        raise RuntimeError(f"Kaggle download failed: {result.stderr}")
    
    print(f"✓ Downloaded to {output_dir}")
    
    # List downloaded files
    files = list(Path(output_dir).glob("*"))
    print(f"  Files: {[f.name for f in files]}")
    
    return files


def upload_to_minio(local_path: str, s3_key: str, endpoint: str, bucket: str, 
                    access_key: str, secret_key: str):
    """Upload model to MinIO"""
    print(f"Uploading to MinIO: s3://{bucket}/{s3_key}")
    
    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    
    with open(local_path, "rb") as f:
        s3.put_object(Bucket=bucket, Key=s3_key, Body=f.read())
    
    print(f"✓ Uploaded to MinIO")
    return f"s3://{bucket}/{s3_key}"


def main():
    parser = argparse.ArgumentParser(description="Download model from Kaggle and upload to MinIO")
    parser.add_argument("--kernel-slug", required=True, help="Kaggle kernel slug")
    parser.add_argument("--run-id", required=True, help="Training run ID")
    parser.add_argument("--username", help="Kaggle username (or use KAGGLE_USERNAME env var)")
    parser.add_argument("--output-dir", default="/tmp/kaggle_output", help="Temporary download directory")
    
    # MinIO configuration
    parser.add_argument("--s3-endpoint", help="MinIO endpoint (or use S3_ENDPOINT env var)")
    parser.add_argument("--s3-bucket", default="alpaca-rl-artifacts", help="S3 bucket name")
    parser.add_argument("--s3-access-key", help="MinIO access key (or use S3_ACCESS_KEY env var)")
    parser.add_argument("--s3-secret-key", help="MinIO secret key (or use S3_SECRET_KEY env var)")
    
    args = parser.parse_args()
    
    # Get configuration from env vars if not provided
    username = args.username or os.getenv("KAGGLE_USERNAME")
    s3_endpoint = args.s3_endpoint or os.getenv("S3_ENDPOINT", "http://localhost:9000")
    s3_access_key = args.s3_access_key or os.getenv("S3_ACCESS_KEY", "minioadmin")
    s3_secret_key = args.s3_secret_key or os.getenv("S3_SECRET_KEY", "minioadmin")
    
    if not username:
        print("✗ Error: KAGGLE_USERNAME not set")
        return 1
    
    try:
        # Download from Kaggle
        files = download_from_kaggle(username, args.kernel_slug, args.output_dir)
        
        # Find model file
        model_files = [f for f in files if f.suffix == ".zip" and "policy" in f.name]
        if not model_files:
            print("✗ Error: No model file found in Kaggle output")
            return 1
        
        model_file = model_files[0]
        print(f"\nFound model: {model_file.name}")
        
        # Upload to MinIO
        s3_key = f"models/kaggle/{args.run_id}/policy_best.zip"
        s3_path = upload_to_minio(
            str(model_file), s3_key, s3_endpoint, args.s3_bucket,
            s3_access_key, s3_secret_key
        )
        
        # Also upload metrics if available
        metrics_files = [f for f in files if f.suffix == ".json" and "metrics" in f.name]
        if metrics_files:
            metrics_file = metrics_files[0]
            metrics_key = f"models/kaggle/{args.run_id}/metrics.json"
            upload_to_minio(
                str(metrics_file), metrics_key, s3_endpoint, args.s3_bucket,
                s3_access_key, s3_secret_key
            )
            print(f"✓ Uploaded metrics")
        
        print(f"\n✓ Model successfully deployed!")
        print(f"  Model path: {s3_path}")
        print(f"\nNext steps:")
        print(f"1. Promote the model via API: POST /rl/policies/{{policy_id}}/promote")
        print(f"2. Deploy for inference using rl-infer service")
        
    except Exception as e:
        print(f"✗ Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
