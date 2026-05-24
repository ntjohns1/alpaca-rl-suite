#!/usr/bin/env python3
"""
Get Kaggle kernel numeric ID from kernel slug.

Usage:
    python scripts/get_kaggle_kernel_id.py nelsonjohns/alpaca-rl-training
"""
import sys
import os
import requests
from requests.auth import HTTPBasicAuth


def get_kernel_id(kernel_slug: str) -> dict:
    """
    Get kernel details including numeric ID via Kaggle REST API.

    Args:
        kernel_slug: Format "username/kernel-slug"

    Returns:
        dict with kernel info including 'id', or None if not found
    """
    username = os.getenv("KAGGLE_USERNAME")
    api_token = os.getenv("KAGGLE_API_TOKEN") or os.getenv("KAGGLE_KEY")  # KAGGLE_KEY is legacy

    if not username or not api_token:
        print("❌ Error: KAGGLE_USERNAME and KAGGLE_API_TOKEN must be set")
        sys.exit(1)

    auth = HTTPBasicAuth(username, api_token)

    # Try the status endpoint first (direct lookup)
    print(f"🔍 Looking up kernel: {kernel_slug}")
    status_resp = requests.get(
        f"https://www.kaggle.com/api/v1/kernels/status/{kernel_slug}",
        auth=auth,
        timeout=120,
    )
    if status_resp.status_code == 200:
        data = status_resp.json()
        print(f"\n✅ Found kernel!")
        print(f"   ID: {data.get('id')}")
        return data

    # Fallback: list user's kernels and search
    print(f"   Status endpoint returned {status_resp.status_code}, falling back to list...")
    list_resp = requests.get(
        "https://www.kaggle.com/api/v1/kernels/list",
        params={"user": username, "pageSize": 100},
        auth=auth,
        timeout=120,
    )

    if list_resp.status_code != 200:
        print(f"❌ API Error: {list_resp.status_code}")
        print(list_resp.text)
        sys.exit(1)

    kernels = list_resp.json()
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
