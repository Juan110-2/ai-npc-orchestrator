from sqlalchemy.orm import Session
from app.models.scenario import Scenario
from app.schemas.scenario import ScenarioCreate

class ScenarioRepository:

    @staticmethod
    def create(db: Session, payload: ScenarioCreate) -> Scenario:
        scenario = Scenario(**payload.dict())
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
