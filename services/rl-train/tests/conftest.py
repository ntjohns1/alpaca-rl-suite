"""
Conftest for rl-train tests.
Mocks heavy optional dependencies before any service module is loaded.
"""
import sys
from unittest.mock import MagicMock

for mod in (
    "observability",
    "prometheus_client",
    "prometheus_fastapi_instrumentator",
    "torch",
    "stable_baselines3",
    "stable_baselines3.common",
    "stable_baselines3.common.callbacks",
    "stable_baselines3.common.monitor",
    "gymnasium",
    "trading_env",
    "boto3",
    "psycopg2",
):
    sys.modules.setdefault(mod, MagicMock())

_pa_mock = MagicMock()
_pa_mock.__version__ = "16.0.0"
sys.modules.setdefault("pyarrow", _pa_mock)
sys.modules.setdefault("pyarrow.parquet", MagicMock())
