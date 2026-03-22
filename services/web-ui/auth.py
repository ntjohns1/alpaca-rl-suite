"""
Authentication middleware and utilities for Keycloak integration.
"""
import logging
import os
from typing import Optional

import requests
from fastapi import HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

log = logging.getLogger(__name__)

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "https://auth.nelsonjohns.com")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "admin")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "alpaca-rl-web-ui")

security = HTTPBearer(auto_error=False)


class KeycloakAuth:
    """Keycloak authentication handler."""
    
    def __init__(self):
        self.public_key: Optional[str] = None
        self.issuer = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}"
        self.jwks_uri = f"{self.issuer}/protocol/openid-connect/certs"
        self.algorithms = ["RS256"]
        
    def get_public_key(self) -> str:
        """Fetch and cache the public key from Keycloak."""
        if self.public_key:
            return self.public_key
            
        try:
            response = requests.get(self.jwks_uri, timeout=10)
            response.raise_for_status()
            jwks = response.json()
            
            if "keys" in jwks and len(jwks["keys"]) > 0:
                key = jwks["keys"][0]
                from jose.backends import RSAKey
                rsa_key = RSAKey(key, self.algorithms[0])
                self.public_key = rsa_key.to_pem().decode("utf-8")
                log.info("Successfully fetched Keycloak public key")
                return self.public_key
            else:
                raise ValueError("No keys found in JWKS response")
                
        except Exception as e:
            log.error(f"Failed to fetch Keycloak public key: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service unavailable"
            )
    
    def verify_token(self, token: str) -> dict:
        """Verify and decode a JWT token."""
        try:
            public_key = self.get_public_key()
            
            payload = jwt.decode(
                token,
                public_key,
                algorithms=self.algorithms,
                issuer=self.issuer,
                options={
                    "verify_signature": True,
                    "verify_aud": False,  # Public clients don't always have aud claim
                    "verify_iss": True,
                    "verify_exp": True,
                }
            )
            
            return payload
            
        except JWTError as e:
            log.warning(f"JWT validation failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
    
    def get_user_info(self, payload: dict) -> dict:
        """Extract user information from token payload."""
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


keycloak_auth = KeycloakAuth()


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = None
) -> dict:
    """
    FastAPI dependency to get the current authenticated user.
    Extracts and validates the JWT token from the Authorization header.
    """
    if credentials is None:
        credentials = await security(request)
    
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    payload = keycloak_auth.verify_token(token)
    user_info = keycloak_auth.get_user_info(payload)
    
    return user_info


async def get_optional_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = None
) -> Optional[dict]:
    """
    Optional authentication - returns user info if token is present and valid,
    None otherwise. Does not raise exceptions.
    """
    if credentials is None:
        credentials = await security(request)
    
    if not credentials:
        return None
    
    try:
        token = credentials.credentials
        payload = keycloak_auth.verify_token(token)
        return keycloak_auth.get_user_info(payload)
    except HTTPException:
        return None


def require_role(role: str):
    """
    Decorator factory for role-based access control.
    Usage: @require_role("rl-admin")
    """
    async def role_checker(user: dict = None) -> dict:
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required"
            )
        
        realm_roles = user.get("realm_access", {}).get("roles", [])
        
        if role not in realm_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required role '{role}' not found"
            )
        
        return user
    
    return role_checker
