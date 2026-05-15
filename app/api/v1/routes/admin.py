"""
Rutas de administración de usuarios.
Solo accesibles para usuarios con role = 'admin'.
"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db
from app.core.auth import verify_supabase_jwt
from app.models.user_profile import UserProfile
from app.repositories.users_repository import UsersRepository
from app.schemas.users import UserProfileResponse, UserProfileUpdate

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_teacher_or_admin(
    db: Session = Depends(get_db),
    payload: dict | None = Depends(verify_supabase_jwt),
) -> UserProfile:
    if payload is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Se requiere autenticación")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token sin sub")

    user = UsersRepository.get_by_id(db, UUID(user_id))
    if not user or user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Se requiere rol teacher o admin")
    return user


def _require_admin(
    db: Session = Depends(get_db),
    payload: dict | None = Depends(verify_supabase_jwt),
) -> UserProfile:
    """
    Dependency que garantiza que el caller es admin.
    - Si auth está desactivado (dev), lanza 403 igualmente para proteger la ruta.
    - Si está activo, valida rol en user_profiles.
    """
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ruta de administración — se requiere autenticación y rol admin",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token sin sub")

    user = UsersRepository.get_by_id(db, UUID(user_id))
    if not user or user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado — se requiere rol admin",
        )
    return user


@router.get("/me", response_model=UserProfileResponse)
def get_my_profile(
    db: Session = Depends(get_db),
    payload: dict | None = Depends(verify_supabase_jwt),
):
    """
    Devuelve el perfil del usuario autenticado (rol incluido).
    Usado por el frontend para conocer el rol real sin depender de user_metadata.
    Ruta: GET /admin/me  (separada de /admin/users/{id} para evitar conflicto de paths)
    """
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token sin sub")

    user = UsersRepository.get_by_id(db, UUID(user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Perfil no encontrado")

    return user


@router.get("/users", response_model=list[UserProfileResponse])
def list_users(
    db: Session = Depends(get_db),
    _admin: UserProfile = Depends(_require_admin),
):
    """Lista todos los usuarios registrados en la plataforma."""
    return UsersRepository.list_all(db)


@router.patch("/users/{user_id}", response_model=UserProfileResponse)
def update_user(
    user_id: UUID,
    body: UserProfileUpdate,
    db: Session = Depends(get_db),
    admin: UserProfile = Depends(_require_admin),
):
    """Actualiza el rol o nombre de un usuario. Un admin no puede quitarse su propio rol."""
    if user_id == admin.id and body.role and body.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes cambiar tu propio rol de admin",
        )

    updated = UsersRepository.update(
        db,
        user_id=user_id,
        role=body.role,
        full_name=body.full_name,
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    return updated


@router.get("/students", response_model=list[UserProfileResponse])
def list_students(
    db: Session = Depends(get_db),
    _caller: UserProfile = Depends(_require_teacher_or_admin),
):
    """Lista todos los usuarios con rol student. Accesible para teacher y admin."""
    return UsersRepository.list_by_role(db, role="student")
