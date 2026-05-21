from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID

from app.api.v1.deps import get_db
from app.schemas.scenario import ScenarioCreate, ScenarioResponse, ScenarioUpdate
from app.repositories.scenario_repository import ScenarioRepository

router = APIRouter(prefix="/scenarios", tags=["scenarios"])

_404 = {404: {"description": "Escenario no encontrado"}}


@router.post(
    "/create",
    response_model=ScenarioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear escenario",
    description=(
        "Crea un nuevo escenario de simulación. "
        "El escenario define la situación narrativa que el personaje simulado (NPC) conoce, "
        "la severidad emocional inicial (1–5), los indicadores de riesgo y las restricciones "
        "de comportamiento."
    ),
    response_description="Escenario creado con su UUID asignado y timestamp.",
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
    description="Devuelve todos los escenarios de simulación registrados en el sistema.",
    response_description="Lista de escenarios.",
)
def list_scenarios(
    db: Session = Depends(get_db),
):
    return ScenarioRepository.list(db)


@router.get(
    "/{scenario_id}",
    response_model=ScenarioResponse,
    summary="Obtener escenario por ID",
    description="Devuelve el detalle completo de un escenario de simulación.",
    response_description="Escenario encontrado.",
    responses=_404,
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
        "Solo se modifican los campos incluidos en el body. "
        "**Nota**: `risk_flags` y `constraints` se reemplazan completamente si se envían."
    ),
    response_description="Escenario actualizado.",
    responses=_404,
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
        "Esta operación no se puede deshacer."
    ),
    responses=_404,
)
def delete_scenario(
    scenario_id: UUID,
    db: Session = Depends(get_db),
):
    deleted = ScenarioRepository.delete(db, scenario_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Scenario not found")
