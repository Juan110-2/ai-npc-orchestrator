"""
Repositorios para rubricas y evaluaciones de sesion.
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models.rubric_definition import RubricDefinition
from app.models.session_evaluation import SessionEvaluation


class RubricsRepository:
    @staticmethod
    def get_active(db: Session, name: str = "rubrica_practica_psicologica") -> Optional[RubricDefinition]:
        """Devuelve la version mas reciente y activa de una rubrica por nombre."""
        return (
            db.query(RubricDefinition)
            .filter(
                RubricDefinition.name == name,
                RubricDefinition.is_active.is_(True),
            )
            .order_by(desc(RubricDefinition.version))
            .first()
        )

    @staticmethod
    def get_by_id(db: Session, rubric_id: UUID) -> Optional[RubricDefinition]:
        return db.query(RubricDefinition).filter(RubricDefinition.id == rubric_id).first()


class EvaluationsRepository:
    @staticmethod
    def get_by_session(db: Session, session_id: UUID) -> Optional[SessionEvaluation]:
        return (
            db.query(SessionEvaluation)
            .filter(SessionEvaluation.session_id == session_id)
            .first()
        )

    @staticmethod
    def list_by_student(db: Session, student_id: UUID, limit: int = 50):
        return (
            db.query(SessionEvaluation)
            .filter(SessionEvaluation.student_id == student_id)
            .order_by(desc(SessionEvaluation.created_at))
            .limit(limit)
            .all()
        )

    @staticmethod
    def upsert_automatic_metrics(
        db: Session,
        *,
        session_id: UUID,
        student_id: Optional[UUID],
        evaluator_id: Optional[UUID] = None,
        rubric_id: Optional[UUID],
        automatic_metrics: dict,
    ) -> SessionEvaluation:
        """Crea o actualiza la parte automatica de la evaluacion."""
        ev = EvaluationsRepository.get_by_session(db, session_id)
        if ev is None:
            ev = SessionEvaluation(
                session_id=session_id,
                student_id=student_id,
                evaluator_id=evaluator_id,
                rubric_id=rubric_id,
                automatic_metrics=automatic_metrics,
                scores={},
                status="draft",
            )
            db.add(ev)
        else:
            ev.automatic_metrics = automatic_metrics
            if student_id and not ev.student_id:
                ev.student_id = student_id
            if evaluator_id and not ev.evaluator_id:
                ev.evaluator_id = evaluator_id
            if rubric_id and not ev.rubric_id:
                ev.rubric_id = rubric_id
        db.commit()
        db.refresh(ev)
        return ev

    @staticmethod
    def submit_teacher_evaluation(
        db: Session,
        *,
        session_id: UUID,
        evaluator_id: UUID,
        scores: dict,
        teacher_feedback: Optional[str],
        status_value: str = "submitted",
    ) -> Optional[SessionEvaluation]:
        ev = EvaluationsRepository.get_by_session(db, session_id)
        if ev is None:
            return None
        ev.evaluator_id = evaluator_id
        ev.scores = scores
        ev.teacher_feedback = teacher_feedback
        ev.status = status_value
        if status_value == "submitted":
            ev.submitted_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(ev)
        return ev
