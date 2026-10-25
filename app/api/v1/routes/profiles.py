from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.deps import ensure_author_or_admin, get_db, require_staff
from app.core.auth import verify_supabase_jwt
from app.models.user_profile import UserProfile
from app.repositories.profile_repository import ProfileRepository
from app.schemas.profile import ProfileCreate, ProfileResponse, ProfileUpdate

router = APIRouter(prefix="/profiles", tags=["profiles"])

_401 = {401: {"description": "Token no enviado o inválido"}}
_403 = {403: {"description": "Se requiere rol `teacher` o `admin`"}}
_403_DELETE = {403: {"description": "Se requiere rol `teacher` o `admin`, y ser el autor del caso o `admin`"}}
_404 = {404: {"description": "Perfil no encontrado"}}


@router.post(
    "/create",
    response_model=ProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear perfil de NPC",
    description=(
        "Crea un nuevo perfil de personaje simulado (NPC). "
        "El perfil define la identidad (`traits`) y el comportamiento conversacional (`behavior`) "
        "del personaje, incluyendo el rango de severidad emocional permitido "
        "(`behavior_min` / `behavior_max`).\n\n"
        "El usuario autenticado queda registrado como autor (`created_by`); "
        "el campo es informativo y no restringe quién puede ver o editar el perfil.\n\n"
        "Requiere JWT y rol `teacher` o `admin`."
    ),
    response_description="Perfil creado con UUID, timestamps y autor.",
    responses={**_401, **_403},
)
def create_profile(
    payload: ProfileCreate,
    db: Session = Depends(get_db),
    user: UserProfile = Depends(require_staff),
):
    return ProfileRepository.create(db, payload, created_by=user.id)


@router.get(
    "/",
    response_model=list[ProfileResponse],
    summary="Listar perfiles",
    description=(
        "Devuelve todos los perfiles de personajes simulados registrados en el sistema.\n\n"
        "Requiere JWT; cualquier usuario autenticado."
    ),
    response_description="Lista de perfiles ordenada por fecha de creación.",
    responses=_401,
    dependencies=[Depends(verify_supabase_jwt)],
)
def get_profiles(
    db: Session = Depends(get_db),
):
    return ProfileRepository.get_all(db)


@router.get(
    "/{profile_id}",
    response_model=ProfileResponse,
    summary="Obtener perfil por ID",
    description=(
        "Devuelve el detalle completo de un perfil de personaje simulado.\n\n"
        "Requiere JWT; cualquier usuario autenticado."
    ),
    response_description="Perfil encontrado.",
    responses={**_401, **_404},
    dependencies=[Depends(verify_supabase_jwt)],
)
def get_profile(
    profile_id: str,
    db: Session = Depends(get_db),
):
    profile = ProfileRepository.get_by_id(db, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.patch(
    "/{profile_id}/update",
    response_model=ProfileResponse,
    summary="Actualizar perfil",
    description=(
        "Actualiza parcialmente un perfil de personaje simulado. "
        "Solo se modifican los campos enviados en el body; los omitidos conservan su valor actual.\n\n"
        "Nota: `traits` y `behavior` se reemplazan por completo si se envían.\n\n"
        "Requiere JWT y rol `teacher` o `admin`."
    ),
    response_description="Perfil actualizado.",
    responses={**_401, **_403, **_404},
    dependencies=[Depends(require_staff)],
)
def update_profile(
    profile_id: str,
    payload: ProfileUpdate,
    db: Session = Depends(get_db),
):
    profile = ProfileRepository.update(db, profile_id, payload)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.delete(
    "/{profile_id}/delete",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar perfil",
    description=(
        "Elimina permanentemente un perfil de personaje simulado. "
        "Esta operación no se puede deshacer y elimina también las sesiones que usan el perfil, "
        "con sus mensajes y evaluaciones.\n\n"
        "Solo puede eliminarlo su autor (`created_by`) o un `admin`; "
        "los perfiles sin autor registrado solo los elimina un `admin`.\n\n"
        "Requiere JWT y rol `teacher` o `admin`."
    ),
    responses={**_401, **_403_DELETE, **_404},
)
def delete_profile(
    profile_id: str,
    db: Session = Depends(get_db),
    user: UserProfile = Depends(require_staff),
):
    item = ProfileRepository.get_by_id(db, profile_id)
    if not item:
        raise HTTPException(status_code=404, detail="Profile not found")
    ensure_author_or_admin(user, item.created_by, "perfil")
    ProfileRepository.delete(db, profile_id)
