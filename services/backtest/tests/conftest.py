"""
Conftest for backtest service tests.
Mocks heavy optional dependencies (opentelemetry, stable_baselines3, torch,
Keycloak) so tests can run without the full production environment.
"""
import os
import sys
from unittest.mock import MagicMock

os.environ.setdefault("KEYCLOAK_URL", "http://localhost:8080")
os.environ.setdefault("KEYCLOAK_REALM", "test")
os.environ.setdefault("KEYCLOAK_CLIENT_ID", "test-client")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

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

fake_keycloak = MagicMock()
fake_keycloak.KeycloakOpenID = MagicMock(return_value=MagicMock(certs=lambda: {"keys": []}))
sys.modules.setdefault("keycloak", fake_keycloak)
