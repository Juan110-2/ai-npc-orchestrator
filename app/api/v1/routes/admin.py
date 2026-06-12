"""
Rutas de administración de usuarios.

Acceso:
  - `admin`: acceso completo a todas las rutas.
  - `teacher`: acceso a la lista de estudiantes.
  - `student`: sin acceso a este módulo.
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


def _get_authenticated_profile(db: Session, payload: dict | None) -> UserProfile:
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token sin sub")

    user = UsersRepository.get_by_id(db, UUID(user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Perfil no encontrado")

    return user


def _require_teacher_or_admin(
    db: Session = Depends(get_db),
    payload: dict | None = Depends(verify_supabase_jwt),
) -> UserProfile:
    user = _get_authenticated_profile(db, payload)
    if user.role not in ("teacher", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol teacher o admin",
        )
    return user


def _require_admin(
    db: Session = Depends(get_db),
    payload: dict | None = Depends(verify_supabase_jwt),
) -> UserProfile:
    """
    Garantiza que el caller tenga rol `admin`.

    Si el JWT es válido pero el perfil local no es admin, responde 403.
    """
    user = _get_authenticated_profile(db, payload)
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado: se requiere rol admin",
        )
    return user


@router.get(
    "/me",
    response_model=UserProfileResponse,
    summary="Obtener perfil autenticado",
    description=(
        "Devuelve el perfil local del usuario autenticado, incluyendo su rol real en la plataforma. "
        "Este endpoint permite al frontend resolver permisos sin depender del `user_metadata` "
        "de Supabase Auth.\n\n"
        "Requiere un JWT válido en `Authorization: Bearer <token>`."
    ),
    response_description="Perfil autenticado con datos básicos y rol.",
    responses={
        401: {"description": "No autenticado o token sin `sub`"},
        404: {"description": "Perfil local no encontrado"},
    },
)
def get_my_profile(
    db: Session = Depends(get_db),
    payload: dict | None = Depends(verify_supabase_jwt),
):
    return _get_authenticated_profile(db, payload)


@router.get(
    "/users",
    response_model=list[UserProfileResponse],
    summary="Listar usuarios",
    description=(
        "Devuelve la lista completa de usuarios registrados en la plataforma. "
        "Solo está disponible para cuentas con rol `admin`."
    ),
    response_description="Lista de perfiles de usuario.",
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
    summary="Actualizar usuario",
    description=(
        "Actualiza parcialmente el rol o el nombre de un usuario.\n\n"
        "Restricción: un administrador no puede degradar su propio rol desde este endpoint."
    ),
    response_description="Perfil de usuario actualizado.",
    responses={
        400: {"description": "Intento de auto-degradación de un admin"},
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
    summary="Listar estudiantes",
    description=(
        "Devuelve todos los usuarios con rol `student`. "
        "Puede ser consultado por `teacher` y `admin`.\n\n"
        "Es útil para asignación de sesiones y revisión docente."
    ),
    response_description="Lista de perfiles con rol `student`.",
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
