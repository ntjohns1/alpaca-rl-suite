"""
Conftest for backtest service tests.
Mocks heavy optional dependencies (opentelemetry, stable_baselines3, torch)
so tests can run without the full production environment.
"""
import sys
from unittest.mock import MagicMock

# ── Mock the local observability module and other heavy deps ────────────────
# This prevents any opentelemetry sub-import chain from being walked.
for mod in (
    "observability",
    "prometheus_client",
    "prometheus_fastapi_instrumentator",
    "stable_baselines3",
    "boto3",
):
    sys.modules.setdefault(mod, MagicMock())
