from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, require_staff
from app.core.auth import verify_supabase_jwt
from app.repositories.scenario_repository import ScenarioRepository
from app.schemas.scenario import ScenarioCreate, ScenarioResponse, ScenarioUpdate

router = APIRouter(prefix="/scenarios", tags=["scenarios"])

_401 = {401: {"description": "Token no enviado o inválido"}}
_403 = {403: {"description": "Se requiere rol `teacher` o `admin`"}}
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
        "Requiere JWT y rol `teacher` o `admin`."
    ),
    response_description="Escenario creado con UUID y timestamp.",
    responses={**_401, **_403},
    dependencies=[Depends(require_staff)],
)
def create_scenario(
    payload: ScenarioCreate,
    db: Session = Depends(get_db),
):
    return ScenarioRepository.create(db, payload)


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
        "Nota: `risk_flags` y `constraints` se reemplazan completamente si se envían.\n\n"
        "Requiere JWT y rol `teacher` o `admin`."
    ),
    response_description="Escenario actualizado.",
    responses={**_401, **_403, **_404},
    dependencies=[Depends(require_staff)],
)
def update_scenario(
    scenario_id: UUID,
    payload: ScenarioUpdate,
    db: Session = Depends(get_db),
):
    scenario = ScenarioRepository.update(db, scenario_id, payload)
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
        "Requiere JWT y rol `teacher` o `admin`."
    ),
    responses={**_401, **_403, **_404},
    dependencies=[Depends(require_staff)],
)
def delete_scenario(
    scenario_id: UUID,
    db: Session = Depends(get_db),
):
    deleted = ScenarioRepository.delete(db, scenario_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Scenario not found")
