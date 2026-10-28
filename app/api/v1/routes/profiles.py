from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.deps import can_manage_case, ensure_author_or_admin, get_db, require_staff
from app.core.auth import verify_supabase_jwt
from app.models.user_profile import UserProfile
from app.repositories.catalog_usage import BLOCKED, NOT_FOUND
from app.repositories.profile_repository import ProfileRepository
from app.schemas.catalog_usage import CatalogUsageResponse
from app.schemas.profile import ProfileCreate, ProfileResponse, ProfileUpdate

router = APIRouter(prefix="/profiles", tags=["profiles"])

_401 = {401: {"description": "Token no enviado o inválido"}}
_403 = {403: {"description": "Se requiere rol `teacher` o `admin`"}}
_403_AUTHOR = {403: {"description": "Se requiere rol `teacher` o `admin`, y ser el autor del caso o `admin`"}}
_409_DELETE = {
    409: {
        "description": (
            "El caso tiene sesiones con actividad registrada (mensajes, evaluación o registros de IA), "
            "o se registró actividad mientras se eliminaba; no se elimina para conservar la trazabilidad"
        )
    }
}
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
        "El usuario autenticado queda registrado como autor (`created_by`). "
        "Cualquier usuario autenticado puede consultar el perfil y los `teacher`/`admin` pueden usarlo "
        "en sesiones, pero solo su autor o un `admin` pueden editarlo o eliminarlo.\n\n"
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
        "Nota: `traits` y `behavior` se reemplazan por completo si se envían. "
        "El autor (`created_by`) no se puede cambiar.\n\n"
        "Solo puede editarlo su autor (`created_by`) o un `admin`; "
        "los perfiles sin autor registrado solo los edita un `admin`. "
        "Si no se cumple, responde 403 y no se modifica nada. "
        "Los demás docentes pueden usar el perfil en sesiones o duplicarlo desde el cliente "
        "(crear uno nuevo a partir de este) para adaptarlo.\n\n"
        "Requiere JWT y rol `teacher` o `admin`."
    ),
    response_description="Perfil actualizado.",
    responses={**_401, **_403_AUTHOR, **_404},
)
def update_profile(
    profile_id: str,
    payload: ProfileUpdate,
    db: Session = Depends(get_db),
    user: UserProfile = Depends(require_staff),
):
    item = ProfileRepository.get_by_id(db, profile_id)
    if not item:
        raise HTTPException(status_code=404, detail="Profile not found")
    ensure_author_or_admin(user, item.created_by, "perfil", "editarlo")
    profile = ProfileRepository.update(db, item.id, payload)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.delete(
    "/{profile_id}/delete",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar perfil",
    description=(
        "Elimina permanentemente un perfil de personaje simulado. "
        "Esta operación no se puede deshacer.\n\n"
        "Una sesión tiene actividad si registra al menos un mensaje de conversación, una evaluación "
        "o una llamada a IA. Si alguna sesión del perfil tiene actividad, no se elimina nada (409), "
        "para conservar la trazabilidad de las prácticas. Si todas sus sesiones están sin uso "
        "(asignadas o creadas pero nunca usadas), se eliminan junto con el perfil en una sola "
        "transacción. Consulta antes `GET /profiles/{profile_id}/usage`.\n\n"
        "Solo puede eliminarlo su autor (`created_by`) o un `admin`; "
        "los perfiles sin autor registrado solo los elimina un `admin`.\n\n"
        "Requiere JWT y rol `teacher` o `admin`."
    ),
    responses={**_401, **_403_AUTHOR, **_404, **_409_DELETE},
)
def delete_profile(
    profile_id: str,
    db: Session = Depends(get_db),
    user: UserProfile = Depends(require_staff),
):
    item = ProfileRepository.get_by_id(db, profile_id)
    if not item:
        raise HTTPException(status_code=404, detail="Profile not found")
    ensure_author_or_admin(user, item.created_by, "perfil", "eliminarlo")
    try:
        result = ProfileRepository.delete_if_unused(db, item.id)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No se pudo eliminar el perfil porque se registró una sesión o actividad "
                "mientras se eliminaba. Revisa su uso e inténtalo de nuevo."
            ),
        )
    if result.status == NOT_FOUND:
        raise HTTPException(status_code=404, detail="Profile not found")
    if result.status == BLOCKED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"El perfil tiene {result.sessions_with_activity} sesión(es) con actividad registrada "
                "y no se puede eliminar, para conservar la trazabilidad de las prácticas."
            ),
        )


@router.get(
    "/{profile_id}/usage",
    response_model=CatalogUsageResponse,
    summary="Uso del perfil por sesiones",
    description=(
        "Indica cuántas sesiones usan el perfil y si se puede eliminar. "
        "Una sesión tiene actividad si registra al menos un mensaje de conversación, una evaluación "
        "o una llamada a IA; las demás se consideran sin uso y se eliminan junto con el perfil.\n\n"
        "`can_delete` es `true` si no hay sesiones con actividad; `allowed` es `true` si el usuario "
        "autenticado es el autor del perfil o `admin`, que son quienes pueden editarlo y eliminarlo "
        "(los perfiles sin autor registrado solo los gestiona un `admin`).\n\n"
        "Requiere JWT y rol `teacher` o `admin`."
    ),
    response_description="Conteo de sesiones del perfil y permisos de eliminación.",
    responses={**_401, **_403, **_404},
)
def get_profile_usage(
    profile_id: UUID,
    db: Session = Depends(get_db),
    user: UserProfile = Depends(require_staff),
):
    item = ProfileRepository.get_by_id(db, profile_id)
    if not item:
        raise HTTPException(status_code=404, detail="Profile not found")
    usage = ProfileRepository.get_usage(db, item.id)
    if usage is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return CatalogUsageResponse(
        total_sessions=usage.total_sessions,
        sessions_with_activity=usage.sessions_with_activity,
        unused_sessions=usage.unused_sessions,
        can_delete=usage.can_delete,
        allowed=can_manage_case(user, item.created_by),
    )
