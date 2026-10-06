"""
Middleware de autenticación JWT para Supabase.

Comportamiento:
- SUPABASE_JWT_SECRET es obligatorio (ver app/core/config.py), salvo que se
  active explícitamente ALLOW_UNSECURE_MOCK_AUTH=true para desarrollo local.
- Los tokens asimétricos (RS256/ES256/...) se validan contra el JWKS de Supabase
  y no dependen de SUPABASE_JWT_SECRET.

Uso en el frontend: el cliente envía el token de sesión de Supabase
en el header Authorization: Bearer <token>.

Instalación del secret:
  SUPABASE_JWT_SECRET se obtiene en Supabase Dashboard → Project Settings → API → JWT Secret.
"""

import base64
import json
import time
import urllib.request
import logging

from fastapi import Request, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.config import (
    SUPABASE_JWT_SECRET,
    SUPABASE_JWT_ISSUER,
    SUPABASE_JWKS_URL,
)

logger = logging.getLogger(__name__)
_security = HTTPBearer(auto_error=False)

_JWKS_CACHE: dict[str, object] = {
    "jwks": None,
    "fetched_at": 0.0,
    "url": None,
}
_JWKS_TTL_SECONDS = 3600

ASYMMETRIC_ALGS = {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}


def _fetch_jwks(jwks_url: str) -> dict:
    with urllib.request.urlopen(jwks_url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_jwk_for_kid(jwks_url: str, kid: str) -> dict | None:
    now = time.time()
    cached_url = _JWKS_CACHE.get("url")
    cached_jwks = _JWKS_CACHE.get("jwks")
    fetched_at = float(_JWKS_CACHE.get("fetched_at") or 0.0)

    if cached_jwks and cached_url == jwks_url and (now - fetched_at) < _JWKS_TTL_SECONDS:
        jwks = cached_jwks
    else:
        jwks = _fetch_jwks(jwks_url)
        _JWKS_CACHE["jwks"] = jwks
        _JWKS_CACHE["url"] = jwks_url
        _JWKS_CACHE["fetched_at"] = now

    keys = jwks.get("keys", []) if isinstance(jwks, dict) else []
    for key in keys:
        if key.get("kid") == kid:
            return key

    # refresco único por si hubo rotación
    jwks = _fetch_jwks(jwks_url)
    _JWKS_CACHE["jwks"] = jwks
    _JWKS_CACHE["url"] = jwks_url
    _JWKS_CACHE["fetched_at"] = now

    keys = jwks.get("keys", []) if isinstance(jwks, dict) else []
    for key in keys:
        if key.get("kid") == kid:
            return key

    return None


def _get_hs256_secret() -> str | bytes:
    if not SUPABASE_JWT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT secret legacy no configurado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return base64.b64decode(SUPABASE_JWT_SECRET, validate=True)
    except Exception:
        return SUPABASE_JWT_SECRET


def _decode_and_verify_token(token: str) -> dict:
    from jose import jwt, jwk

    header = jwt.get_unverified_header(token)
    alg = header.get("alg")
    kid = header.get("kid")

    if not alg:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sin algoritmo",
            headers={"WWW-Authenticate": "Bearer"},
        )

    unverified = jwt.get_unverified_claims(token)
    issuer = unverified.get("iss")

    # 1) Tokens asimetricos modernos: ES256 / RS256 / etc.
    if alg in ASYMMETRIC_ALGS:
        # El issuer y el JWKS salen siempre de la configuración del servidor:
        # tomarlos del propio token permitiría firmarlo con una clave del atacante.
        expected_issuer = SUPABASE_JWT_ISSUER
        if not expected_issuer:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Issuer no configurado en el servidor",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if issuer != expected_issuer:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Issuer del token no coincide",
                headers={"WWW-Authenticate": "Bearer"},
            )

        jwks_url = SUPABASE_JWKS_URL or f"{expected_issuer.rstrip('/')}/.well-known/jwks.json"

        if not jwks_url or not kid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token sin JWKS URL o kid",
                headers={"WWW-Authenticate": "Bearer"},
            )

        jwk_key = _get_jwk_for_kid(jwks_url, kid)
        if not jwk_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No se encontro la clave publica para el token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        public_key = jwk.construct(jwk_key, algorithm=alg).to_pem().decode("utf-8")

        return jwt.decode(
            token,
            public_key,
            algorithms=[alg],
            issuer=expected_issuer,
            options={"verify_aud": False},
        )

    # 2) Compatibilidad temporal con legacy HS256
    if alg == "HS256":
        secret = _get_hs256_secret()
        return jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=f"Algoritmo JWT no soportado: {alg}",
        headers={"WWW-Authenticate": "Bearer"},
    )


def verify_supabase_token(token: str) -> dict:
    try:
        return _decode_and_verify_token(token)
    except HTTPException:
        raise
    except Exception as exc:
        issuer = None
        alg = None
        try:
            from jose import jwt

            header = jwt.get_unverified_header(token)
            claims = jwt.get_unverified_claims(token)
            alg = header.get("alg")
            issuer = claims.get("iss")
        except Exception:
            pass

        logger.warning("[auth] JWT decode failed: %s; alg=%s; iss=%s", exc, alg, issuer)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def verify_supabase_jwt(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> dict:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header requerido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return verify_supabase_token(credentials.credentials)
