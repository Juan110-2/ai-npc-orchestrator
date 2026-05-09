"""
Middleware de autenticación JWT para Supabase.

Comportamiento:
- Si SUPABASE_JWT_SECRET está definido en el entorno, el middleware valida
  el Bearer token de cada request entrante.
- Si no está definido, el middleware se desactiva completamente.
  Esto permite desarrollo local sin auth sin cambiar código.

Uso en el frontend: el cliente envía el token de sesión de Supabase
en el header Authorization: Bearer <token>.

Instalación del secret:
  SUPABASE_JWT_SECRET se obtiene en Supabase Dashboard → Project Settings → API → JWT Secret.
"""

from fastapi import Request, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.config import SUPABASE_JWT_SECRET

_security = HTTPBearer(auto_error=False)


async def verify_supabase_jwt(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = None,
) -> dict | None:
    """
    Dependency de FastAPI que valida el JWT de Supabase.
    Se puede usar por ruta con Depends(verify_supabase_jwt).

    Si SUPABASE_JWT_SECRET no está definido, retorna None (sin auth).
    Si está definido pero el token es inválido, lanza 401.
    """
    if not SUPABASE_JWT_SECRET:
        # Auth desactivado — modo desarrollo
        return None

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header requerido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        from jose import jwt, JWTError

        payload = jwt.decode(
            credentials.credentials,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False},  # Supabase no siempre incluye aud
        )
        return payload

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
