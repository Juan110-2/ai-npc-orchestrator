from uuid import UUID
from sqlalchemy.orm import Session

from app.models.sessions import Session as SessionModel


class SessionRepository:

    @staticmethod
    def start(
        db: Session,
        profile_id,
        scenario,
        user_id: UUID | None = None,
    ) -> SessionModel:
        session = SessionModel(
            profile_id=profile_id,
            scenario_id=scenario.id,
            current_severity=scenario.severity,
            user_id=user_id,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    @staticmethod
    def get_by_id(db: Session, session_id) -> SessionModel | None:
        return db.query(SessionModel).filter(SessionModel.id == session_id).first()

    @staticmethod
    def list_recent(db: Session, limit: int = 50) -> list[SessionModel]:
        return (
            db.query(SessionModel)
            .order_by(SessionModel.started_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def list_by_user(db: Session, user_id: UUID, limit: int = 50) -> list[SessionModel]:
        """Devuelve las sesiones de un usuario específico, ordenadas por fecha descendente."""
        return (
            db.query(SessionModel)
            .filter(SessionModel.user_id == user_id)
            .order_by(SessionModel.started_at.desc())
            .limit(limit)
            .all()
        )
