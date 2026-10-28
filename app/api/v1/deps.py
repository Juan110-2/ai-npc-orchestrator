from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.auth import verify_supabase_jwt, verify_supabase_token
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


def resolve_authenticated_user(
    *,
    db,
    credentials: HTTPAuthorizationCredentials | None,
) -> UserProfile:
    """
    Resuelve el usuario autenticado de forma consistente.

    Sin credenciales, con token inválido, sin `sub` válido o sin perfil local
    lanza 401; nunca retorna None.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header requerido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_supabase_token(credentials.credentials)
    user_id = get_subject_id(payload)

    user = UsersRepository.get_by_id(db, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario autenticado sin perfil asociado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


STAFF_ROLES = ("teacher", "admin")


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

    Se permite al dueño de la sesión o a `teacher` y `admin`.
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


def require_staff(
    db=Depends(get_db),
    payload: dict = Depends(verify_supabase_jwt),
) -> UserProfile:
    """
    Exige JWT válido y rol `teacher` o `admin`.

    Sin token o sin `sub` válido -> 401; sin perfil local o con otro rol -> 403.
    Retorna el perfil del usuario para reutilizarlo en la ruta.
    """
    user = UsersRepository.get_by_id(db, get_subject_id(payload))
    if user is None or user.role not in STAFF_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol teacher o admin",
        )
    return user


def can_delete_case(user: UserProfile, created_by) -> bool:
    """
    Si el usuario puede eliminar el caso: es admin o es su autor (`created_by`).

    Un caso sin autor registrado (creado antes de guardar `created_by`) solo lo elimina un admin.
    """
    if user.role == "admin":
        return True
    return created_by is not None and str(created_by) == str(user.id)


def ensure_author_or_admin(user: UserProfile, created_by, resource: str) -> None:
    """Solo el autor del caso o un admin pueden eliminarlo; si no, 403."""
    if not can_delete_case(user, created_by):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Solo el autor del {resource} o un admin pueden eliminarlo",
        )
