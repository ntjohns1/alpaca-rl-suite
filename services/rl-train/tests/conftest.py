"""
Conftest for rl-train tests.
Mocks heavy optional dependencies and Keycloak auth before any service module
is loaded.
"""
import os
import sys
from unittest.mock import MagicMock

os.environ.setdefault("KEYCLOAK_URL", "http://localhost:8080")
os.environ.setdefault("KEYCLOAK_REALM", "test")
os.environ.setdefault("KEYCLOAK_CLIENT_ID", "test-client")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

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

fake_keycloak = MagicMock()
fake_keycloak.KeycloakOpenID = MagicMock(return_value=MagicMock(certs=lambda: {"keys": []}))
sys.modules.setdefault("keycloak", fake_keycloak)
