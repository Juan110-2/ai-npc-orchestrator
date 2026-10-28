from sqlalchemy.orm import Session
from app.models.scenario import Scenario
from app.models.sessions import Session as SessionModel
from app.repositories.catalog_usage import CaseUsage, DeleteResult, delete_case_if_unused, get_case_usage
from app.schemas.scenario import ScenarioCreate, ScenarioUpdate

class ScenarioRepository:

    @staticmethod
    def create(db: Session, payload: ScenarioCreate, created_by=None) -> Scenario:
        scenario = Scenario(**payload.model_dump(), created_by=created_by)
        db.add(scenario)
        db.commit()
        db.refresh(scenario)
        return scenario

    @staticmethod
    def list(db: Session):
        return db.query(Scenario).order_by(Scenario.created_at.desc()).all()

    @staticmethod
    def get_by_id(db: Session, scenario_id):
        return db.query(Scenario).filter(Scenario.id == scenario_id).first()

    @staticmethod
    def update(db: Session, scenario_id, payload: ScenarioUpdate):
        scenario = ScenarioRepository.get_by_id(db, scenario_id)
        if not scenario:
            return None

        data = payload.model_dump(exclude_unset=True)
        for key, value in data.items():
            setattr(scenario, key, value)

        db.commit()
        db.refresh(scenario)
        return scenario

    @staticmethod
    def delete_if_unused(db: Session, scenario_id) -> DeleteResult:
        """Borra el escenario y sus sesiones sin uso; si alguna tiene actividad, no toca nada."""
        return delete_case_if_unused(db, Scenario, SessionModel.scenario_id, scenario_id)

    @staticmethod
    def get_usage(db: Session, scenario_id) -> CaseUsage | None:
        return get_case_usage(db, Scenario, SessionModel.scenario_id, scenario_id)
