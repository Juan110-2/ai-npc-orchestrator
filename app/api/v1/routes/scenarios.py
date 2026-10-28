from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.deps import can_manage_case, ensure_author_or_admin, get_db, require_staff
from app.core.auth import verify_supabase_jwt
from app.models.user_profile import UserProfile
from app.repositories.catalog_usage import BLOCKED, NOT_FOUND
from app.repositories.scenario_repository import ScenarioRepository
from app.schemas.catalog_usage import CatalogUsageResponse
from app.schemas.scenario import ScenarioCreate, ScenarioResponse, ScenarioUpdate

router = APIRouter(prefix="/scenarios", tags=["scenarios"])

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
_404 = {404: {"description": "Escenario no encontrado"}}


@router.post(
    "/create",
    response_model=ScenarioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear escenario",
    description=(
        "Crea un nuevo escenario de simulación. "
        "El escenario define la situación narrativa que el personaje simulado conoce, "
        "la severidad emocional inicial, los indicadores de riesgo y las restricciones "
        "de comportamiento.\n\n"
        "El usuario autenticado queda registrado como autor (`created_by`). "
        "Cualquier usuario autenticado puede consultar el escenario y los `teacher`/`admin` pueden usarlo "
        "en sesiones, pero solo su autor o un `admin` pueden editarlo o eliminarlo.\n\n"
        "Requiere JWT y rol `teacher` o `admin`."
    ),
    response_description="Escenario creado con UUID, timestamp y autor.",
    responses={**_401, **_403},
)
def create_scenario(
    payload: ScenarioCreate,
    db: Session = Depends(get_db),
    user: UserProfile = Depends(require_staff),
):
    return ScenarioRepository.create(db, payload, created_by=user.id)


@router.get(
    "/",
    response_model=list[ScenarioResponse],
    summary="Listar escenarios",
    description=(
        "Devuelve todos los escenarios de simulación registrados en el sistema.\n\n"
        "Requiere JWT; cualquier usuario autenticado."
    ),
    response_description="Lista de escenarios.",
    responses=_401,
    dependencies=[Depends(verify_supabase_jwt)],
)
def list_scenarios(
    db: Session = Depends(get_db),
):
    return ScenarioRepository.list(db)


@router.get(
    "/{scenario_id}",
    response_model=ScenarioResponse,
    summary="Obtener escenario por ID",
    description=(
        "Devuelve el detalle completo de un escenario de simulación.\n\n"
        "Requiere JWT; cualquier usuario autenticado."
    ),
    response_description="Escenario encontrado.",
    responses={**_401, **_404},
    dependencies=[Depends(verify_supabase_jwt)],
)
def get_scenario(
    scenario_id: UUID,
    db: Session = Depends(get_db),
):
    scenario = ScenarioRepository.get_by_id(db, scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return scenario


@router.patch(
    "/{scenario_id}/update",
    response_model=ScenarioResponse,
    summary="Actualizar escenario",
    description=(
        "Actualiza parcialmente un escenario de simulación. "
        "Solo se modifican los campos incluidos en el body.\n\n"
        "Nota: `risk_flags` y `constraints` se reemplazan completamente si se envían. "
        "El autor (`created_by`) no se puede cambiar.\n\n"
        "Solo puede editarlo su autor (`created_by`) o un `admin`; "
        "los escenarios sin autor registrado solo los edita un `admin`. "
        "Si no se cumple, responde 403 y no se modifica nada. "
        "Los demás docentes pueden usar el escenario en sesiones o duplicarlo desde el cliente "
        "(crear uno nuevo a partir de este) para adaptarlo.\n\n"
        "Requiere JWT y rol `teacher` o `admin`."
    ),
    response_description="Escenario actualizado.",
    responses={**_401, **_403_AUTHOR, **_404},
)
def update_scenario(
    scenario_id: UUID,
    payload: ScenarioUpdate,
    db: Session = Depends(get_db),
    user: UserProfile = Depends(require_staff),
):
    item = ScenarioRepository.get_by_id(db, scenario_id)
    if not item:
        raise HTTPException(status_code=404, detail="Scenario not found")
    ensure_author_or_admin(user, item.created_by, "escenario", "editarlo")
    scenario = ScenarioRepository.update(db, item.id, payload)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return scenario


@router.delete(
    "/{scenario_id}/delete",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar escenario",
    description=(
        "Elimina permanentemente un escenario de simulación. "
        "Esta operación no se puede deshacer.\n\n"
        "Una sesión tiene actividad si registra al menos un mensaje de conversación, una evaluación "
        "o una llamada a IA. Si alguna sesión del escenario tiene actividad, no se elimina nada (409), "
        "para conservar la trazabilidad de las prácticas. Si todas sus sesiones están sin uso "
        "(asignadas o creadas pero nunca usadas), se eliminan junto con el escenario en una sola "
        "transacción. Consulta antes `GET /scenarios/{scenario_id}/usage`.\n\n"
        "Solo puede eliminarlo su autor (`created_by`) o un `admin`; "
        "los escenarios sin autor registrado solo los elimina un `admin`.\n\n"
        "Requiere JWT y rol `teacher` o `admin`."
    ),
    responses={**_401, **_403_AUTHOR, **_404, **_409_DELETE},
)
def delete_scenario(
    scenario_id: UUID,
    db: Session = Depends(get_db),
    user: UserProfile = Depends(require_staff),
):
    item = ScenarioRepository.get_by_id(db, scenario_id)
    if not item:
        raise HTTPException(status_code=404, detail="Scenario not found")
    ensure_author_or_admin(user, item.created_by, "escenario", "eliminarlo")
    try:
        result = ScenarioRepository.delete_if_unused(db, item.id)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No se pudo eliminar el escenario porque se registró una sesión o actividad "
                "mientras se eliminaba. Revisa su uso e inténtalo de nuevo."
            ),
        )
    if result.status == NOT_FOUND:
        raise HTTPException(status_code=404, detail="Scenario not found")
    if result.status == BLOCKED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"El escenario tiene {result.sessions_with_activity} sesión(es) con actividad registrada "
                "y no se puede eliminar, para conservar la trazabilidad de las prácticas."
            ),
        )


@router.get(
    "/{scenario_id}/usage",
    response_model=CatalogUsageResponse,
    summary="Uso del escenario por sesiones",
    description=(
        "Indica cuántas sesiones usan el escenario y si se puede eliminar. "
        "Una sesión tiene actividad si registra al menos un mensaje de conversación, una evaluación "
        "o una llamada a IA; las demás se consideran sin uso y se eliminan junto con el escenario.\n\n"
        "`can_delete` es `true` si no hay sesiones con actividad; `allowed` es `true` si el usuario "
        "autenticado es el autor del escenario o `admin`, que son quienes pueden editarlo y eliminarlo "
        "(los escenarios sin autor registrado solo los gestiona un `admin`).\n\n"
        "Requiere JWT y rol `teacher` o `admin`."
    ),
    response_description="Conteo de sesiones del escenario y permisos de eliminación.",
    responses={**_401, **_403, **_404},
)
def get_scenario_usage(
    scenario_id: UUID,
    db: Session = Depends(get_db),
    user: UserProfile = Depends(require_staff),
):
    item = ScenarioRepository.get_by_id(db, scenario_id)
    if not item:
        raise HTTPException(status_code=404, detail="Scenario not found")
    usage = ScenarioRepository.get_usage(db, item.id)
    if usage is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return CatalogUsageResponse(
        total_sessions=usage.total_sessions,
        sessions_with_activity=usage.sessions_with_activity,
        unused_sessions=usage.unused_sessions,
        can_delete=usage.can_delete,
        allowed=can_manage_case(user, item.created_by),
    )
