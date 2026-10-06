from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.auth import verify_supabase_jwt, verify_supabase_token
from app.core.config import SUPABASE_JWT_SECRET
from app.core.database import SessionLocal
from app.models.user_profile import UserProfile
from app.repositories.sessions_repository import SessionRepository
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


STAFF_ROLES = ("teacher", "admin", "superadmin")


def get_user_role(db, user_id: UUID) -> str:
    """Rol del usuario autenticado; sin perfil en `user_profiles` se trata como `student`."""
    user = UsersRepository.get_by_id(db, user_id)
    return user.role if user else "student"


def get_subject_id(payload: dict) -> UUID:
    """UUID del usuario (`sub`) del token; 401 si falta o no es un UUID (p. ej. claves anon/service_role)."""
    try:
        return UUID(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sin usuario valido",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_session_access(
    session_id: UUID,
    db=Depends(get_db),
    payload: dict = Depends(verify_supabase_jwt),
):
    """
    Exige JWT válido y autoriza el acceso a una sesión concreta.

    Se permite al dueño de la sesión o a `teacher`, `admin` y `superadmin`.
    Sesión inexistente -> 404; cualquier otro caso -> 403.
    Retorna la sesión para reutilizarla en la ruta.
    """
    user_id = get_subject_id(payload)
    session = SessionRepository.get_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    if session.user_id is not None and session.user_id == user_id:
        return session

    if get_user_role(db, user_id) not in STAFF_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a esta sesión",
        )
    return session
