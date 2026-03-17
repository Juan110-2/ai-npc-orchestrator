from sqlalchemy.orm import Session
from app.models.sessions import Session as SessionModel

class SessionRepository:

    @staticmethod
    def list(db: Session):
        return db.query(SessionModel).order_by(SessionModel.created_at.desc()).all()

    @staticmethod
    def start(db: Session, profile_id, scenario):
        session = SessionModel(
            profile_id=profile_id,
            scenario_id=scenario.id,
            current_severity=scenario.severity
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    @staticmethod
    def get_by_id(db: Session, session_id):
        return db.query(SessionModel).filter(SessionModel.id == session_id).first()

    @staticmethod
    def list_recent(db: Session, limit: int = 20):
        return (
            db.query(SessionModel)
            .order_by(SessionModel.started_at.desc())
            .limit(limit)
            .all()
        )
