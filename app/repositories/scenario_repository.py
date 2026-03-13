from sqlalchemy.orm import Session
from app.models.scenario import Scenario
from app.models.sessions import Session as SessionModel
from app.models.conversation_message import ConversationMessage
from app.schemas.scenario import ScenarioCreate, ScenarioUpdate

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

    @staticmethod
    def update(db: Session, scenario_id, payload: ScenarioUpdate):
        scenario = ScenarioRepository.get_by_id(db, scenario_id)
        if not scenario:
            return None

        data = payload.dict(exclude_unset=True)
        for key, value in data.items():
            setattr(scenario, key, value)

        db.commit()
        db.refresh(scenario)
        return scenario

    @staticmethod
    def delete(db: Session, scenario_id) -> bool:
        scenario = ScenarioRepository.get_by_id(db, scenario_id)
        if not scenario:
            return False

        linked_session_ids = [
            row[0]
            for row in db.query(SessionModel.id)
            .filter(SessionModel.scenario_id == scenario.id)
            .all()
        ]

        if linked_session_ids:
            db.query(ConversationMessage).filter(
                ConversationMessage.session_id.in_(linked_session_ids)
            ).delete(synchronize_session=False)
            db.query(SessionModel).filter(
                SessionModel.id.in_(linked_session_ids)
            ).delete(synchronize_session=False)

        db.delete(scenario)
        db.commit()
        return True
