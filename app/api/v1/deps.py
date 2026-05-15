from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.auth import verify_supabase_token
from app.core.database import SessionLocal

_bearer = HTTPBearer(auto_error=False)


def get_db():
    """Provee una sesión de base de datos por solicitud HTTP."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def optional_jwt(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict | None:
    """
    Extrae y valida el JWT si está presente en el header Authorization.
    Retorna None si no hay token (modo dev sin auth).
    """
    if credentials is None:
        return None
    try:
        return verify_supabase_token(credentials.credentials)
    except Exception:
        return None
