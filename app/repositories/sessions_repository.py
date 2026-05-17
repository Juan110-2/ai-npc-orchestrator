from datetime import datetime, timezone
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

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _apply_status(q, status: str | None):
        if status in ('active', 'completed', 'terminated'):
            return q.filter(SessionModel.status == status)
        return q

    # ── all sessions (admin / no-auth) ────────────────────────────────────────

    @staticmethod
    def count_recent(db: Session, status: str | None = None) -> int:
        q = db.query(SessionModel)
        return SessionRepository._apply_status(q, status).count()

    @staticmethod
    def list_recent(
        db: Session,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> list[SessionModel]:
        q = db.query(SessionModel)
        q = SessionRepository._apply_status(q, status)
        return q.order_by(SessionModel.started_at.desc()).offset(offset).limit(limit).all()

    # ── sessions where I am the trainee ──────────────────────────────────────

    @staticmethod
    def count_by_user(db: Session, user_id: UUID, status: str | None = None) -> int:
        q = db.query(SessionModel).filter(SessionModel.user_id == user_id)
        return SessionRepository._apply_status(q, status).count()

    @staticmethod
    def list_by_user(
        db: Session,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> list[SessionModel]:
        q = db.query(SessionModel).filter(SessionModel.user_id == user_id)
        q = SessionRepository._apply_status(q, status)
        return q.order_by(SessionModel.started_at.desc()).offset(offset).limit(limit).all()

    # ── sessions I assigned to others (teacher view) ──────────────────────────

    @staticmethod
    def count_assigned_to_others(
        db: Session,
        assigned_by: UUID,
        self_id: UUID,
        status: str | None = None,
    ) -> int:
        q = db.query(SessionModel).filter(
            SessionModel.assigned_by == assigned_by,
            SessionModel.user_id != self_id,
        )
        return SessionRepository._apply_status(q, status).count()

    @staticmethod
    def list_assigned_to_others(
        db: Session,
        assigned_by: UUID,
        self_id: UUID,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> list[SessionModel]:
        q = db.query(SessionModel).filter(
            SessionModel.assigned_by == assigned_by,
            SessionModel.user_id != self_id,
        )
        q = SessionRepository._apply_status(q, status)
        return q.order_by(SessionModel.started_at.desc()).offset(offset).limit(limit).all()

    # ── time tracking ─────────────────────────────────────────────────────────

    @staticmethod
    def add_time_delta(
        db: Session, session_id: UUID, delta_seconds: int
    ) -> SessionModel | None:
        """
        Adds delta_seconds to accumulated_seconds.
        Marks time_source='explicit' on the first call.
        Idempotent if the session is already closed.
        """
        session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if not session:
            return None
        if session.ended_at:
            return session  # session already closed — ignore silently
        session.accumulated_seconds = (session.accumulated_seconds or 0) + delta_seconds
        if session.time_source != 'explicit':
            session.time_source = 'explicit'
        session.last_interaction_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(session)
        return session

    # ── kept for /active endpoint ─────────────────────────────────────────────

    @staticmethod
    def list_by_assigned_by(db: Session, assigned_by: UUID, limit: int = 100) -> list[SessionModel]:
        return (
            db.query(SessionModel)
            .filter(SessionModel.assigned_by == assigned_by)
            .order_by(SessionModel.started_at.desc())
            .limit(limit)
            .all()
        )
