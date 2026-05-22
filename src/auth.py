from __future__ import annotations

import os
import time
from functools import lru_cache
from typing import Any, Dict, Mapping, Optional

import jwt
from fastapi import HTTPException, Request, status
from jwt import InvalidTokenError, PyJWKClient


AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "false").strip().lower() == "true"
JWT_ISSUER = os.getenv("JWT_ISSUER", "").strip()
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "").strip()
JWT_JWKS_URL = os.getenv("JWT_JWKS_URL", "").strip()
JWT_TENANT_CLAIM = os.getenv("JWT_TENANT_CLAIM", "https://captureos/tenant").strip()
JWT_ROLE_CLAIM = os.getenv("JWT_ROLE_CLAIM", "https://captureos/role").strip()
JWT_EMAIL_CLAIM = os.getenv("JWT_EMAIL_CLAIM", "email").strip()
JWT_NAME_CLAIM = os.getenv("JWT_NAME_CLAIM", "name").strip()
JWT_CLOCK_SKEW_SECONDS = int(os.getenv("JWT_CLOCK_SKEW_SECONDS", "60"))


def authenticate_request(request: Request) -> Dict[str, Any]:
    token = _bearer_token(request)
    if not token:
        if AUTH_REQUIRED:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token is required.")
        return {"auth_mode": "demo_header_context", "claims": {}}

    claims = _decode_jwt(token)
    return {
        "auth_mode": "jwt",
        "claims": claims,
        "tenant_slug": _claim(claims, JWT_TENANT_CLAIM),
        "email": _claim(claims, JWT_EMAIL_CLAIM),
        "display_name": _claim(claims, JWT_NAME_CLAIM),
        "role": _claim(claims, JWT_ROLE_CLAIM),
        "subject": claims.get("sub"),
    }


def _decode_jwt(token: str) -> Dict[str, Any]:
    if not JWT_JWKS_URL or not JWT_ISSUER or not JWT_AUDIENCE:
        if AUTH_REQUIRED:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="JWT enforcement is enabled but JWT_JWKS_URL, JWT_ISSUER, or JWT_AUDIENCE is missing.",
            )
        return _decode_unverified(token)

    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256", "ES256"],
            audience=JWT_AUDIENCE,
            issuer=JWT_ISSUER,
            leeway=JWT_CLOCK_SKEW_SECONDS,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token.") from exc

    if int(claims.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token is expired.")
    return dict(claims)


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    return PyJWKClient(JWT_JWKS_URL, cache_keys=True, max_cached_keys=16)


def _decode_unverified(token: str) -> Dict[str, Any]:
    try:
        return dict(jwt.decode(token, options={"verify_signature": False, "verify_aud": False}))
    except InvalidTokenError:
        return {}


def _bearer_token(request: Request) -> Optional[str]:
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization must use Bearer scheme.")
    return value.strip()


def _claim(claims: Mapping[str, Any], name: str) -> Optional[str]:
    value = claims.get(name)
    if value is None:
        return None
    if isinstance(value, list):
        return str(value[0]) if value else None
    return str(value)
