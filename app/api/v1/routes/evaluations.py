"""
Endpoints de evaluacion pedagogica (Capitulo 5).

Trazabilidad: cada evaluacion esta vinculada a session_id y student_id.
El docente (rol teacher o admin) revisa la transcripcion + metricas
automaticas y completa la rubrica. El estudiante puede leer su propia
evaluacion una vez submitted.

Endpoints:
  POST /evaluation/{session_id}/auto   - recalcula metricas automaticas
  GET  /evaluation/{session_id}        - lee evaluacion completa
  PUT  /evaluation/{session_id}        - teacher/admin llena scores + feedback
  GET  /evaluation/student/{id}        - historial de un estudiante
  GET  /evaluation/rubric/active       - rubrica vigente
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db
from app.core.config import SUPABASE_JWT_SECRET
from app.models.user_profile import UserProfile
from app.repositories.evaluations_repository import (
    EvaluationsRepository,
    RubricsRepository,
)
from app.repositories.sessions_repository import SessionRepository
from app.repositories.users_repository import UsersRepository
from app.services.evaluation_service import compute_overall_score, run_auto_evaluation

router = APIRouter(prefix="/evaluation", tags=["evaluation"])

_security = HTTPBearer(auto_error=False)


def _get_current_user(
    db: Session,
    credentials: Optional[HTTPAuthorizationCredentials],
) -> Optional[UserProfile]:
    """Si auth desactivada (modo dev), devuelve None. Si activa, devuelve UserProfile."""
    if not SUPABASE_JWT_SECRET:
        return None
    if credentials is None:
        return None
    try:
        from jose import jwt
        unverified = jwt.get_unverified_claims(credentials.credentials)
        user_id_str = unverified.get("sub")
        if not user_id_str:
            return None
        return UsersRepository.get_by_id(db, UUID(user_id_str))
    except Exception:
        return None


def _require_staff_or_dev(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> Optional[UserProfile]:
    if not SUPABASE_JWT_SECRET:
        return None
    user = _get_current_user(db, credentials)
    if not user or user.role not in ("teacher", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo teachers y admins pueden ejecutar esta operacion",
        )
    return user


# ----- Schemas ---------------------------------------------------------------

class TeacherEvaluationInput(BaseModel):
    scores: dict[str, float] = Field(default_factory=dict)
    teacher_feedback: Optional[str] = None
    status: str = "submitted"  # draft | submitted


class EvaluationResponse(BaseModel):
    id: str
    session_id: str
    student_id: Optional[str]
    evaluator_id: Optional[str]
    rubric_id: Optional[str]
    status: str
    automatic_metrics: dict
    scores: dict
    teacher_feedback: Optional[str]
    overall_score: Optional[float]
    created_at: Optional[str]
    updated_at: Optional[str]
    submitted_at: Optional[str]


def _serialize_evaluation(db: Session, ev) -> EvaluationResponse:
    overall = None
    if ev.scores and ev.rubric_id:
        rubric = RubricsRepository.get_by_id(db, ev.rubric_id)
        if rubric:
            overall = compute_overall_score(ev.scores, rubric.criteria)
    return EvaluationResponse(
        id=str(ev.id),
        session_id=str(ev.session_id),
        student_id=str(ev.student_id) if ev.student_id else None,
        evaluator_id=str(ev.evaluator_id) if ev.evaluator_id else None,
        rubric_id=str(ev.rubric_id) if ev.rubric_id else None,
        status=ev.status,
        automatic_metrics=ev.automatic_metrics or {},
        scores=ev.scores or {},
        teacher_feedback=ev.teacher_feedback,
        overall_score=overall,
        created_at=ev.created_at.isoformat() if ev.created_at else None,
        updated_at=ev.updated_at.isoformat() if ev.updated_at else None,
        submitted_at=ev.submitted_at.isoformat() if ev.submitted_at else None,
    )


# ----- Endpoints -------------------------------------------------------------

@router.get("/rubric/active")
def get_active_rubric(db: Session = Depends(get_db)):
    """Rubrica vigente. Publica para que el frontend la renderice."""
    rubric = RubricsRepository.get_active(db)
    if not rubric:
        raise HTTPException(status_code=404, detail="No hay rubrica activa")
    return {
        "id": str(rubric.id),
        "version": rubric.version,
        "name": rubric.name,
        "description": rubric.description,
        "criteria": rubric.criteria,
        "is_active": rubric.is_active,
    }


@router.post("/{session_id}/auto", response_model=EvaluationResponse)
def run_auto(
    session_id: UUID,
    db: Session = Depends(get_db),
    _: Optional[UserProfile] = Depends(_require_staff_or_dev),
):
    """
    Recalcula las metricas automaticas de la sesion y las upsertea en
    session_evaluations. Idempotente. Llamar al cerrar la sesion o cuando
    el docente abra el panel de evaluacion.
    """
    ev = run_auto_evaluation(db, session_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Sesion no encontrada")
    return _serialize_evaluation(db, ev)


@router.get("/{session_id}", response_model=EvaluationResponse)
def get_evaluation(
    session_id: UUID,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
):
    """
    Lee la evaluacion. Permisos:
      - teacher/admin: pueden leer cualquier evaluacion.
      - student: solo si es el dueno de la sesion.
      - sin auth (dev): pasa.
    """
    ev = EvaluationsRepository.get_by_session(db, session_id)
    if not ev:
        # Auto-crear con metricas si la sesion existe
        ev = run_auto_evaluation(db, session_id)
        if not ev:
            raise HTTPException(status_code=404, detail="Sesion no encontrada")

    if SUPABASE_JWT_SECRET:
        user = _get_current_user(db, credentials)
        if user is None:
            raise HTTPException(status_code=401, detail="Auth requerida")
        if user.role not in ("teacher", "admin") and ev.student_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="Solo el dueno de la sesion o staff puede ver esta evaluacion",
            )

    return _serialize_evaluation(db, ev)


@router.put("/{session_id}", response_model=EvaluationResponse)
def submit_teacher_evaluation(
    session_id: UUID,
    body: TeacherEvaluationInput,
    db: Session = Depends(get_db),
    user: Optional[UserProfile] = Depends(_require_staff_or_dev),
):
    """
    Submit (o draft) de la evaluacion del docente. Si auth esta activa,
    se exige rol teacher/admin.
    """
    if body.status not in ("draft", "submitted", "reviewed"):
        raise HTTPException(status_code=400, detail="Status invalido")

    evaluator_uuid = user.id if user else None
    # Si no hay user (modo dev) y no nos dieron evaluator, no marcamos
    if evaluator_uuid is None:
        # Permitir en modo dev con id fantasma null
        from uuid import UUID as _UUID
        evaluator_uuid = _UUID("00000000-0000-0000-0000-000000000000")

    ev = EvaluationsRepository.submit_teacher_evaluation(
        db,
        session_id=session_id,
        evaluator_id=evaluator_uuid,
        scores=body.scores,
        teacher_feedback=body.teacher_feedback,
        status_value=body.status,
    )
    if not ev:
        raise HTTPException(
            status_code=404,
            detail="Evaluacion no existe. Ejecuta primero POST /evaluation/{id}/auto",
        )
    return _serialize_evaluation(db, ev)


@router.get("/")
def list_evaluations(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
):
    """
    Lista general de evaluaciones para la vista de Inicio de /evaluacion.
      - student: solo las suyas (filtradas por student_id == user.id).
      - teacher/admin: todas.
      - sin auth (dev): todas.
    """
    from app.models.session_evaluation import SessionEvaluation
    from app.models.profile import Profile
    from app.models.sessions import Session as SessionModel
    from sqlalchemy import desc

    user = _get_current_user(db, credentials) if SUPABASE_JWT_SECRET else None

    q = (
        db.query(SessionEvaluation, SessionModel, Profile)
        .outerjoin(SessionModel, SessionModel.id == SessionEvaluation.session_id)
        .outerjoin(Profile, Profile.id == SessionModel.profile_id)
        .order_by(desc(SessionEvaluation.created_at))
    )

    if SUPABASE_JWT_SECRET and user is not None and user.role == "student":
        q = q.filter(SessionEvaluation.student_id == user.id)

    rows = q.limit(200).all()
    out = []
    for (e, s, p_row) in rows:
        out.append({
            "id": str(e.id),
            "session_id": str(e.session_id),
            "student_id": str(e.student_id) if e.student_id else None,
            "status": e.status,
            "patient_name": p_row.name if p_row else None,
            "started_at": s.started_at.isoformat() if s and s.started_at else None,
            "ended_at": s.ended_at.isoformat() if s and s.ended_at else None,
            "automatic_metrics": e.automatic_metrics or {},
            "scores": e.scores or {},
            "submitted_at": e.submitted_at.isoformat() if e.submitted_at else None,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        })
    return out


@router.get("/student/{student_id}")
def list_student_evaluations(
    student_id: UUID,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
):
    """
    Historial de evaluaciones de un estudiante. Permisos:
      - teacher/admin: cualquier estudiante.
      - student: solo si pide su propio id.
      - sin auth (dev): pasa.
    """
    if SUPABASE_JWT_SECRET:
        user = _get_current_user(db, credentials)
        if user is None:
            raise HTTPException(status_code=401, detail="Auth requerida")
        if user.role not in ("teacher", "admin") and user.id != student_id:
            raise HTTPException(
                status_code=403,
                detail="Solo puedes ver tus propias evaluaciones",
            )

    evs = EvaluationsRepository.list_by_student(db, student_id)
    return [
        {
            "id": str(e.id),
            "session_id": str(e.session_id),
            "status": e.status,
            "automatic_metrics": e.automatic_metrics or {},
            "scores": e.scores or {},
            "teacher_feedback": e.teacher_feedback,
            "submitted_at": e.submitted_at.isoformat() if e.submitted_at else None,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in evs
    ]
