#!/usr/bin/env python3
"""
Get Kaggle kernel metadata including id_no using the API directly.
"""
import json
import requests

# Kaggle credentials
username = "nelsonjohns"
api_key = "KGAT_2e11e55db108a0ed454f0bff1ca24fd3"

# Get kernel metadata
kernel_slug = "nelsonjohns/alpaca-rl-training"

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
