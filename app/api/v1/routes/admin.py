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


@router.get(
    "/me",
    response_model=UserProfileResponse,
    summary="Obtener perfil propio 🔒",
    description=(
        "Devuelve el perfil del usuario autenticado, incluyendo su rol en la plataforma. "
        "El frontend lo usa para conocer el rol real (`student`, `teacher`, `admin`) "
        "sin depender del campo `user_metadata` de Supabase Auth.\n\n"
        "Requiere un JWT válido de Supabase (`Authorization: Bearer <token>`)."
    ),
    response_description="Perfil del usuario autenticado con su rol.",
    responses={
        401: {"description": "No autenticado o token sin campo `sub`"},
        404: {"description": "Perfil de usuario no encontrado en la base de datos"},
    },
)
def get_my_profile(
    db: Session = Depends(get_db),
    payload: dict | None = Depends(verify_supabase_jwt),
):
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token sin sub")

    user = UsersRepository.get_by_id(db, UUID(user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Perfil no encontrado")

    return user


@router.get(
    "/users",
    response_model=list[UserProfileResponse],
    summary="Listar todos los usuarios 🔒 admin",
    description=(
        "Devuelve la lista completa de usuarios registrados en la plataforma. "
        "Solo accesible para usuarios con rol `admin`."
    ),
    response_description="Lista de usuarios con id, email, nombre y rol.",
    responses={
        401: {"description": "No autenticado"},
        403: {"description": "Se requiere rol `admin`"},
    },
)
def list_users(
    db: Session = Depends(get_db),
    _admin: UserProfile = Depends(_require_admin),
):
    return UsersRepository.list_all(db)


@router.patch(
    "/users/{user_id}",
    response_model=UserProfileResponse,
    summary="Actualizar usuario 🔒 admin",
    description=(
        "Actualiza el rol o nombre de un usuario. Solo accesible para `admin`.\n\n"
        "**Restricción**: un administrador no puede cambiar su propio rol a uno inferior."
    ),
    response_description="Usuario actualizado.",
    responses={
        400: {"description": "El admin intenta quitarse su propio rol"},
        401: {"description": "No autenticado"},
        403: {"description": "Se requiere rol `admin`"},
        404: {"description": "Usuario no encontrado"},
    },
)
def update_user(
    user_id: UUID,
    body: UserProfileUpdate,
    db: Session = Depends(get_db),
    admin: UserProfile = Depends(_require_admin),
):
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


@router.get(
    "/students",
    response_model=list[UserProfileResponse],
    summary="Listar estudiantes 🔒 teacher / admin",
    description=(
        "Devuelve todos los usuarios con rol `student`. "
        "Accesible para `teacher` y `admin`. "
        "Útil para que un docente seleccione a quién asignar una sesión."
    ),
    response_description="Lista de usuarios con rol `student`.",
    responses={
        401: {"description": "No autenticado"},
        403: {"description": "Se requiere rol `teacher` o `admin`"},
    },
)
def list_students(
    db: Session = Depends(get_db),
    _caller: UserProfile = Depends(_require_teacher_or_admin),
):
    return UsersRepository.list_by_role(db, role="student")
