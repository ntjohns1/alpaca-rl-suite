"""
Shared Keycloak JWT authentication for FastAPI services.

Verifies bearer tokens against a Keycloak realm's JWKS. Caches signing keys
per `kid` and refreshes the cache when a token references an unknown key,
so realm key rotation does not require a service restart.

Validates audience by accepting tokens where `client_id in aud` OR
`azp == client_id` (Keycloak public-client tokens often omit `aud`).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from jose.backends import RSAKey
from keycloak import KeycloakOpenID

log = logging.getLogger(__name__)

_JWKS_REFRESH_MIN_INTERVAL_S = 5.0


class KeycloakAuth:
    """Per-kid JWKS cache + token verification for a single Keycloak realm."""

    def __init__(self, server_url: str, realm: str, client_id: str):
        if not server_url:
            raise ValueError("KEYCLOAK_URL is required")
        if not realm:
            raise ValueError("KEYCLOAK_REALM is required")
        if not client_id:
            raise ValueError("KEYCLOAK_CLIENT_ID is required")

        self.server_url = server_url.rstrip("/")
        self.realm = realm
        self.client_id = client_id
        self.issuer = f"{self.server_url}/realms/{realm}"
        self.algorithms = ["RS256"]

        self._oidc = KeycloakOpenID(
            server_url=self.server_url,
            client_id=client_id,
            realm_name=realm,
        )
        self._keys_by_kid: dict[str, str] = {}
        self._lock = threading.Lock()
        self._last_refresh: float = 0.0

    def _refresh_jwks(self) -> None:
        with self._lock:
            now = time.monotonic()
            if self._keys_by_kid and (now - self._last_refresh) < _JWKS_REFRESH_MIN_INTERVAL_S:
                return
            try:
                jwks = self._oidc.certs()
            except Exception as e:
                log.error("Failed to fetch JWKS from %s: %s", self.issuer, e)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Authentication service unavailable",
                )

            new_keys: dict[str, str] = {}
            for jwk in jwks.get("keys", []):
                kid = jwk.get("kid")
                if not kid or jwk.get("kty") != "RSA":
                    continue
                if jwk.get("use") not in (None, "sig"):
                    continue
                try:
                    pem = RSAKey(jwk, self.algorithms[0]).to_pem().decode("utf-8")
                except Exception as e:
                    log.warning("Skipping unusable JWK kid=%s: %s", kid, e)
                    continue
                new_keys[kid] = pem

            if not new_keys:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="No usable signing keys in JWKS",
                )

            self._keys_by_kid = new_keys
            self._last_refresh = now
            log.info("Refreshed JWKS: %d signing keys cached", len(new_keys))

    def _get_key_for_kid(self, kid: str) -> str:
        key = self._keys_by_kid.get(kid)
        if key is not None:
            return key
        self._refresh_jwks()
        key = self._keys_by_kid.get(kid)
        if key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unknown token signing key",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return key

    def verify_token(self, token: str) -> dict:
        try:
            header = jwt.get_unverified_header(token)
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Malformed authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        kid = header.get("kid")
        if not kid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing kid header",
                headers={"WWW-Authenticate": "Bearer"},
            )

        public_key = self._get_key_for_kid(kid)

        try:
            payload = jwt.decode(
                token,
                public_key,
                algorithms=self.algorithms,
                issuer=self.issuer,
                options={
                    "verify_signature": True,
                    "verify_aud": False,
                    "verify_iss": True,
                    "verify_exp": True,
                },
            )
        except JWTError as e:
            log.warning("JWT validation failed: %s", e)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        aud = payload.get("aud", [])
        if isinstance(aud, str):
            aud = [aud]
        azp = payload.get("azp")
        if self.client_id not in aud and azp != self.client_id:
            log.warning(
                "Token rejected: client_id=%s not in aud=%s and azp=%s",
                self.client_id, aud, azp,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token not intended for this client",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return payload

    @staticmethod
    def user_info(payload: dict) -> dict:
        return {
            "sub": payload.get("sub"),
            "email": payload.get("email"),
            "preferred_username": payload.get("preferred_username"),
            "name": payload.get("name"),
            "given_name": payload.get("given_name"),
            "family_name": payload.get("family_name"),
            "realm_access": payload.get("realm_access", {}),
            "resource_access": payload.get("resource_access", {}),
        }


def keycloak_auth_from_env() -> KeycloakAuth:
    """Build a KeycloakAuth from env vars. Fails fast if any are missing."""
    return KeycloakAuth(
        server_url=os.environ.get("KEYCLOAK_URL", ""),
        realm=os.environ.get("KEYCLOAK_REALM", ""),
        client_id=os.environ.get("KEYCLOAK_CLIENT_ID", ""),
    )


_security = HTTPBearer(auto_error=False)


def make_auth_dependencies(auth: KeycloakAuth):
    """Build FastAPI dependencies bound to a KeycloakAuth instance."""

    async def get_current_user(
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
    ) -> dict:
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        payload = auth.verify_token(credentials.credentials)
        user = auth.user_info(payload)
        request.state.user = user
        return user

    async def get_optional_user(
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
    ) -> Optional[dict]:
        if credentials is None:
            return None
        try:
            payload = auth.verify_token(credentials.credentials)
        except HTTPException as e:
            if e.status_code == status.HTTP_401_UNAUTHORIZED:
                return None
            raise
        user = auth.user_info(payload)
        request.state.user = user
        return user

    def require_role(role: str):
        async def role_checker(user: dict = Depends(get_current_user)) -> dict:
            roles = user.get("realm_access", {}).get("roles", [])
            if role not in roles:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Required role '{role}' not found",
                )
            return user
        return role_checker

    return get_current_user, get_optional_user, require_role
