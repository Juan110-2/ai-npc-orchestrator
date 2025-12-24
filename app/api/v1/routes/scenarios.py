from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID

from app.api.v1.deps import get_db
from app.schemas.scenario import ScenarioCreate, ScenarioResponse
from app.repositories.scenario_repository import ScenarioRepository

router = APIRouter(prefix="/scenarios", tags=["scenarios"])

@router.post("/create", response_model=ScenarioResponse)
def create_scenario(payload: ScenarioCreate, db: Session = Depends(get_db)):
    return ScenarioRepository.create(db, payload)

@router.get("/", response_model=list[ScenarioResponse])
def list_scenarios(db: Session = Depends(get_db)):
    return ScenarioRepository.list(db)

@router.get("/{scenario_id}", response_model=ScenarioResponse)
def get_scenario(scenario_id: UUID, db: Session = Depends(get_db)):
    scenario = ScenarioRepository.get_by_id(db, scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return scenario
