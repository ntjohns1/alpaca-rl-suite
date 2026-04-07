"""
Shared feature column definitions used across rl-train, feature-builder,
dataset-builder, and kaggle-orchestrator services.

Single source of truth — import from here instead of redefining locally.
"""

TECHNICAL_COLS = [
    "ret_1d", "ret_2d", "ret_5d", "ret_10d", "ret_21d",
    "rsi", "macd", "atr", "stoch", "ultosc",
]

SHARADAR_COLS = [
    "pe", "pb", "ps", "evebitda", "marketcap_log",
    "roe", "roa", "debt_equity", "revenue_growth", "fcf_yield",
]

ALL_FEATURE_COLS = TECHNICAL_COLS + SHARADAR_COLS

VALID_FEATURE_MODES = ("precomputed", "compute")
