"""
Web UI authentication shim.

Real implementation lives in `services/shared/keycloak_auth.py` so every
backend service can share the same JWKS cache + audience-validation logic.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from keycloak_auth import (  # noqa: E402  (sys.path manipulation above)
    KeycloakAuth,
    keycloak_auth_from_env,
    make_auth_dependencies,
)

keycloak_auth = keycloak_auth_from_env()
get_current_user, get_optional_user, require_role = make_auth_dependencies(keycloak_auth)

__all__ = [
    "KeycloakAuth",
    "keycloak_auth",
    "get_current_user",
    "get_optional_user",
    "require_role",
]
