from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.auth import verify_supabase_token
from app.core.config import SUPABASE_JWT_SECRET
from app.core.database import SessionLocal
from app.models.user_profile import UserProfile
from app.repositories.users_repository import UsersRepository

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
    except HTTPException:
        raise


def resolve_authenticated_user(
    *,
    db,
    credentials: HTTPAuthorizationCredentials | None,
    allow_missing_credentials: bool = True,
) -> UserProfile | None:
    """
    Resuelve el usuario autenticado de forma consistente.

    - Si auth está desactivada, retorna None.
    - Si no hay credenciales y están permitidas, retorna None.
    - Si el token es inválido o no existe el perfil local, lanza 401.
    """
    if not SUPABASE_JWT_SECRET:
        return None

    if credentials is None:
        if allow_missing_credentials:
            return None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header requerido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_supabase_token(credentials.credentials)
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sin subject valido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = UsersRepository.get_by_id(db, UUID(user_id_str))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario autenticado sin perfil asociado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user
