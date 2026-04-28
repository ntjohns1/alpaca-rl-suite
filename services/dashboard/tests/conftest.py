"""
Conftest for dashboard tests.
Mocks heavy optional dependencies and Keycloak auth before any service module
is loaded.
"""
import os
import sys
from unittest.mock import MagicMock

# Required by main.py at import time.
os.environ.setdefault("KEYCLOAK_URL", "http://localhost:8080")
os.environ.setdefault("KEYCLOAK_REALM", "test")
os.environ.setdefault("KEYCLOAK_CLIENT_ID", "test-client")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

for mod in (
    "observability",
    "prometheus_client",
    "prometheus_fastapi_instrumentator",
    "boto3",
):
    sys.modules.setdefault(mod, MagicMock())

# Stub python-keycloak so we don't make real network calls during tests.
fake_keycloak = MagicMock()
fake_keycloak.KeycloakOpenID = MagicMock(return_value=MagicMock(certs=lambda: {"keys": []}))
sys.modules.setdefault("keycloak", fake_keycloak)
