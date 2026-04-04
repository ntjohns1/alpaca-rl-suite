#!/usr/bin/env python3
"""
Get Kaggle kernel metadata including id_no using the API directly.
"""
import json
import os
import sys
import requests

# Kaggle credentials from environment
username = os.getenv("KAGGLE_USERNAME")
api_key = os.getenv("KAGGLE_KEY")

if not username or not api_key:
    print("❌ Error: KAGGLE_USERNAME and KAGGLE_KEY environment variables must be set")
    print("   Set them using: export KAGGLE_USERNAME=your_username")
    print("                   export KAGGLE_KEY=your_api_key")
    sys.exit(1)

# Get kernel metadata
kernel_slug = f"{username}/alpaca-rl-training"

url = f"https://www.kaggle.com/api/v1/kernels/status/{kernel_slug}"

response = requests.get(url, auth=(username, api_key))

if response.status_code == 200:
    data = response.json()
    print(json.dumps(data, indent=2))
    
    # Try to find id_no
    if 'id' in data:
        print(f"\n✅ Kernel ID: {data['id']}")
else:
    print(f"❌ Error {response.status_code}: {response.text}")
    
    # Try alternate endpoint
    print("\nTrying alternate endpoint...")
    url2 = f"https://www.kaggle.com/api/v1/kernels/list?user={username}"
    response2 = requests.get(url2, auth=(username, api_key))
    
    if response2.status_code == 200:
        kernels = response2.json()
        for kernel in kernels:
            if kernel.get('ref') == kernel_slug:
                print(f"\n✅ Found kernel!")
                print(json.dumps(kernel, indent=2))
                break
