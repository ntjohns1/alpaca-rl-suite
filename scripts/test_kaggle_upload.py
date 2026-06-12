#!/usr/bin/env python3
"""
Quick test: can kagglehub authenticate and upload a dataset?

Usage (on the server with KAGGLE_USERNAME + KAGGLE_KEY/KAGGLE_API_TOKEN set):

  # If only KAGGLE_API_TOKEN is set, bridge it:
  export KAGGLE_KEY="${KAGGLE_API_TOKEN}"

  python3 test_kaggle_upload.py
"""
import os
import sys
import tempfile

# ── 1. Check credentials ─────────────────────────────────────────────
username = os.environ.get("KAGGLE_USERNAME", "")
key = os.environ.get("KAGGLE_KEY", "") or os.environ.get("KAGGLE_API_TOKEN", "")

print(f"KAGGLE_USERNAME = {username!r}")
print(f"KAGGLE_KEY      = {'set (' + str(len(key)) + ' chars)' if key else 'NOT SET'}")
print(f"KAGGLE_API_TOKEN= {'set' if os.environ.get('KAGGLE_API_TOKEN') else 'NOT SET'}")

if not username or not key:
    print("\nERROR: KAGGLE_USERNAME and KAGGLE_KEY (or KAGGLE_API_TOKEN) must be set.")
    sys.exit(1)

# Bridge if needed
if not os.environ.get("KAGGLE_KEY"):
    os.environ["KAGGLE_KEY"] = key
    print("  -> Bridged KAGGLE_API_TOKEN to KAGGLE_KEY")

# ── 2. Test kagglehub import + auth ──────────────────────────────────
try:
    import kagglehub
    print(f"\nkagglehub version: {kagglehub.__version__}")
except ImportError:
    print("\nERROR: kagglehub not installed. Run: pip install kagglehub")
    sys.exit(1)

# ── 3. Create a tiny test CSV ────────────────────────────────────────
with tempfile.TemporaryDirectory() as tmpdir:
    csv_path = os.path.join(tmpdir, "test_upload.csv")
    with open(csv_path, "w") as f:
        f.write("date,close\n2024-01-02,100.0\n2024-01-03,101.5\n")

    slug = f"{username}/alpaca-rl-upload-test"
    print(f"\nAttempting upload to: https://kaggle.com/datasets/{slug}")
    print(f"  File: {csv_path}")

    try:
        kagglehub.dataset_upload(
            handle=slug,
            local_dataset_dir=tmpdir,
            version_notes="automated auth test",
        )
        print("\nSUCCESS: Upload completed!")
    except Exception as e:
        print(f"\nFAILED: {e}")
        sys.exit(1)
