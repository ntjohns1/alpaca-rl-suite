"""
Conftest for rl-train tests.
Mocks heavy optional dependencies before any service module is loaded.
"""
import sys
from unittest.mock import MagicMock

# torch must use a real class for Tensor so scipy's issubclass() check doesn't
# blow up with "issubclass() arg 2 must be a class" during collection.
_torch_mock = MagicMock()
_torch_mock.Tensor = type("Tensor", (), {})
sys.modules.setdefault("torch", _torch_mock)

for mod in (
    "observability",
    "prometheus_client",
    "prometheus_fastapi_instrumentator",
    "stable_baselines3",
    "stable_baselines3.common",
    "stable_baselines3.common.callbacks",
    "stable_baselines3.common.monitor",
    "boto3",
    "psycopg2",
):
    sys.modules.setdefault(mod, MagicMock())
