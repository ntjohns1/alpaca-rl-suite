"""
Conftest for kaggle-orchestrator tests.
Mocks heavy optional dependencies before any service module is loaded.
"""
import sys
from unittest.mock import MagicMock

for mod in (
    "observability",
    "prometheus_client",
    "prometheus_fastapi_instrumentator",
    "kaggle",
    "boto3",
):
    sys.modules.setdefault(mod, MagicMock())
