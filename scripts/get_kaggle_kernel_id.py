#!/usr/bin/env python3
"""
Get Kaggle kernel numeric ID from kernel slug.

Usage:
    python scripts/get_kaggle_kernel_id.py nelsonjohns/alpaca-rl-training
"""
import sys
import os
import requests

def get_kernel_metadata_via_cli(kernel_slug: str) -> dict:
    """
    Get kernel metadata using Kaggle CLI.
    This is more reliable than the API for getting id_no.
    """
    import tempfile
    import json
    import subprocess
    
    print(f"🔍 Pulling kernel metadata via CLI: {kernel_slug}")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            # Pull kernel metadata only (not the code)
            result = subprocess.run(
                ["kaggle", "kernels", "pull", "-p", tmpdir, "-k", kernel_slug, "-m"],
                capture_output=True,
                text=True,
                check=True
            )
            
            # Read the metadata file
            metadata_path = f"{tmpdir}/kernel-metadata.json"
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
            
            print(f"\n✅ Found kernel metadata!")
            print(f"   Title: {metadata.get('title')}")
            print(f"   ID: {metadata.get('id')}")
            print(f"   ID Number: {metadata.get('id_no')}")
            print(f"   Language: {metadata.get('language')}")
            print(f"   GPU Enabled: {metadata.get('enable_gpu')}")
            print(f"   Dataset Sources: {metadata.get('dataset_sources', [])}")
            
            return metadata
            
        except subprocess.CalledProcessError as e:
            print(f"❌ CLI Error: {e.stderr}")
            return None
        except FileNotFoundError:
            print(f"❌ Metadata file not found")
            return None


def get_kernel_id(kernel_slug: str) -> dict:
    """
    Get kernel details including numeric ID.
    
    Args:
        kernel_slug: Format "username/kernel-slug"
    
    Returns:
        dict with kernel info including 'id'
    """
    # Try CLI method first (more reliable)
    metadata = get_kernel_metadata_via_cli(kernel_slug)
    if metadata and metadata.get('id_no'):
        return metadata
    
    # Fallback to API method
    username = os.getenv("KAGGLE_USERNAME")
    api_token = os.getenv("KAGGLE_API_TOKEN")
    
    if not username or not api_token:
        print("❌ Error: KAGGLE_USERNAME and KAGGLE_API_TOKEN must be set")
        sys.exit(1)
    
    # Kaggle API endpoint
    url = f"https://www.kaggle.com/api/v1/kernels/list"
    
    headers = {
        "Authorization": f"Bearer {api_token}"
    }
    
    params = {
        "user": username,
        "pageSize": 100
    }
    
    print(f"🔍 Searching for kernel via API: {kernel_slug}")
    
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code != 200:
        print(f"❌ API Error: {response.status_code}")
        print(response.text)
        sys.exit(1)
    
    kernels = response.json()
    
    # Find matching kernel
    for kernel in kernels:
        if kernel.get("ref") == kernel_slug:
            print(f"\n✅ Found kernel!")
            print(f"   Title: {kernel.get('title')}")
            print(f"   Slug: {kernel.get('ref')}")
            print(f"   ID: {kernel.get('id')}")
            print(f"   URL: https://www.kaggle.com/code/{kernel_slug}")
            
            return kernel
    
    print(f"\n❌ Kernel not found: {kernel_slug}")
    print(f"\nAvailable kernels:")
    for kernel in kernels[:10]:
        print(f"  - {kernel.get('ref')} (ID: {kernel.get('id')})")
    
    return None


def main():
    if len(sys.argv) < 2:
        print("Usage: python get_kaggle_kernel_id.py <kernel-slug>")
        print("Example: python get_kaggle_kernel_id.py nelsonjohns/alpaca-rl-training")
        sys.exit(1)
    
    kernel_slug = sys.argv[1]
    get_kernel_id(kernel_slug)


if __name__ == "__main__":
    main()
