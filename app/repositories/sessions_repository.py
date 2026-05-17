from uuid import UUID
from sqlalchemy.orm import Session

from app.models.sessions import Session as SessionModel


class SessionRepository:

    @staticmethod
    def start(
        db: Session,
        profile_id,
        scenario,
        profile=None,
        user_id: UUID | None = None,
        assigned_by: UUID | None = None,
    ) -> SessionModel:
        b = (profile.behavior or {}) if profile and hasattr(profile, 'behavior') else {}
        b_min = float(b.get('behavior_min', 0.0))
        b_max = float(b.get('behavior_max', 5.0))
        if b_min >= b_max:
            b_min, b_max = 0.0, 5.0
        # base_severity: severidad inicial real, ya acotada al rango del perfil.
        # current_severity arranca igual; base_severity nunca cambia durante la sesión.
        initial_sev = max(b_min, min(b_max, float(scenario.severity)))

        session = SessionModel(
            profile_id=profile_id,
            scenario_id=scenario.id,
            current_severity=initial_sev,
            base_severity=initial_sev,
            user_id=user_id,
            assigned_by=assigned_by,
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
        """Sesiones asignadas a un estudiante especifico."""
        return (
            db.query(SessionModel)
            .filter(SessionModel.user_id == user_id)
            .order_by(SessionModel.started_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def list_by_assigned_by(db: Session, assigned_by: UUID, limit: int = 50) -> list[SessionModel]:
        """Sesiones creadas/asignadas por un profesor especifico."""
        return (
            db.query(SessionModel)
            .filter(SessionModel.assigned_by == assigned_by)
            .order_by(SessionModel.started_at.desc())
            .limit(limit)
            .all()
        )
