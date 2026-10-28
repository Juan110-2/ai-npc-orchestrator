"""
Endpoints de evaluación pedagógica.
"""
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import can_access_session, get_db, get_subject_id, get_user_role, require_staff
from app.core.auth import verify_supabase_jwt
from app.models.user_profile import UserProfile
from app.repositories.evaluations_repository import EvaluationsRepository, RubricsRepository
from app.repositories.sessions_repository import SessionRepository
from app.services.evaluation.service import compute_overall_score, run_auto_evaluation

router = APIRouter(
    prefix="/evaluation",
    tags=["evaluation"],
    dependencies=[Depends(verify_supabase_jwt)],
)
logger = logging.getLogger(__name__)


def _ensure_staff_session_access(db: Session, user: UserProfile, session_id: UUID):
    """Carga la sesión (404 si no existe) y exige que el staff pueda acceder a ella (403 si no)."""
    session = SessionRepository.get_by_id(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Sesion no encontrada")
    if not can_access_session(user.role, user.id, session):
        raise HTTPException(
            status_code=403,
            detail="Solo el docente que asigno la sesion o un admin puede acceder a esta evaluacion",
        )
    return session


def _evaluation_visibility_filter(role: str, user_id: UUID):
    """
    Condición SQL de las evaluaciones que el usuario puede listar; `None` si puede ver todas.

    `teacher`: las suyas (como estudiante o dueño de la sesión) o las de sesiones que asignó.
    Otros roles: solo donde es el estudiante.
    """
    from app.models.session_evaluation import SessionEvaluation
    from app.models.sessions import Session as SessionModel
    from sqlalchemy import or_

    if role == "admin":
        return None
    if role == "teacher":
        return or_(
            SessionEvaluation.student_id == user_id,
            SessionModel.user_id == user_id,
            SessionModel.assigned_by == user_id,
        )
    return SessionEvaluation.student_id == user_id


class TeacherEvaluationInput(BaseModel):
    scores: dict[str, float] = Field(default_factory=dict)
    teacher_feedback: Optional[str] = None
    status: str = "submitted"

    model_config = {
        "json_schema_extra": {
            "example": {
                "scores": {"escucha_activa": 4.5, "empatía": 4.0},
                "teacher_feedback": "Buena validación emocional, pero faltó profundizar.",
                "status": "submitted",
            }
        }
    }


class RubricResponse(BaseModel):
    id: str
    version: int
    name: str
    description: str | None = None
    criteria: list[dict]
    is_active: bool

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "f6a7b8c9-d0e1-2345-abcd-456789012345",
                "version": 1,
                "name": "Rúbrica base",
                "description": "Rúbrica principal para evaluación docente.",
                "criteria": [
                    {"key": "escucha_activa", "label": "Escucha activa", "weight": 0.3, "max_score": 5},
                    {"key": "empatía", "label": "Empatía", "weight": 0.4, "max_score": 5},
                ],
                "is_active": True,
            }
        }
    }


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

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "e5f6a7b8-c9d0-1234-efab-345678901234",
                "session_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
                "student_id": "d4e5f6a7-b8c9-0123-defa-234567890123",
                "evaluator_id": "f7a8b9c0-d1e2-3456-abcd-567890123456",
                "rubric_id": "f6a7b8c9-d0e1-2345-abcd-456789012345",
                "status": "submitted",
                "automatic_metrics": {"turns_total": 8, "closing_kind": "success"},
                "scores": {"escucha_activa": 4.5, "empatía": 4.0},
                "teacher_feedback": "Buena validación emocional, pero faltó profundizar.",
                "overall_score": 4.2,
                "created_at": "2025-05-10T09:35:00+00:00",
                "updated_at": "2025-05-10T09:40:00+00:00",
                "submitted_at": "2025-05-10T09:40:00+00:00",
            }
        }
    }


class EvaluationListItemResponse(BaseModel):
    id: str
    session_id: str
    student_id: str | None = None
    student_name: str | None = None
    assigned_by_id: str | None = None
    assigned_by_name: str | None = None
    status: str
    patient_name: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    automatic_metrics: dict
    scores: dict
    submitted_at: str | None = None
    created_at: str | None = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "e5f6a7b8-c9d0-1234-efab-345678901234",
                "session_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
                "student_id": "d4e5f6a7-b8c9-0123-defa-234567890123",
                "student_name": "Ana Martínez",
                "assigned_by_id": "f7a8b9c0-d1e2-3456-abcd-567890123456",
                "assigned_by_name": "Docente Demo",
                "status": "submitted",
                "patient_name": "María García",
                "started_at": "2025-05-10T09:00:00+00:00",
                "ended_at": "2025-05-10T09:30:00+00:00",
                "automatic_metrics": {"turns_total": 8, "closing_kind": "success"},
                "scores": {"escucha_activa": 4.5, "empatía": 4.0},
                "submitted_at": "2025-05-10T09:40:00+00:00",
                "created_at": "2025-05-10T09:35:00+00:00",
            }
        }
    }


class StudentEvaluationHistoryItemResponse(BaseModel):
    id: str
    session_id: str
    status: str
    automatic_metrics: dict
    scores: dict
    teacher_feedback: str | None = None
    submitted_at: str | None = None
    created_at: str | None = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "e5f6a7b8-c9d0-1234-efab-345678901234",
                "session_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
                "status": "submitted",
                "automatic_metrics": {"turns_total": 8, "closing_kind": "success"},
                "scores": {"escucha_activa": 4.5, "empatía": 4.0},
                "teacher_feedback": "Buena validación emocional, pero faltó profundizar.",
                "submitted_at": "2025-05-10T09:40:00+00:00",
                "created_at": "2025-05-10T09:35:00+00:00",
            }
        }
    }


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


@router.get(
    "/rubric/active",
    response_model=RubricResponse,
    summary="Obtener rúbrica vigente",
    description=(
        "Devuelve la definición de la rúbrica de evaluación activa. "
        "Requiere un JWT válido (cualquier rol); el frontend lo usa para renderizar formularios y resultados."
    ),
    response_description="Rúbrica activa con criterios y pesos.",
    responses={
        401: {"description": "Token no enviado o inválido"},
        404: {"description": "No hay rúbrica activa configurada"},
    },
)
def get_active_rubric(db: Session = Depends(get_db)):
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


@router.post(
    "/{session_id}/auto",
    response_model=EvaluationResponse,
    summary="Recalcular métricas automáticas",
    description=(
        "Recalcula las métricas automáticas de una sesión y las persiste en `session_evaluations`. "
        "Puede ejecutarse varias veces sin efectos secundarios funcionales.\n\n"
        "Requiere rol `teacher` o `admin`; el `teacher` solo en sesiones propias o que asignó."
    ),
    response_description="Evaluación actualizada con métricas automáticas recalculadas.",
    responses={
        401: {"description": "Token no enviado o inválido"},
        403: {"description": "Se requiere rol `teacher` o `admin`, o la sesión no es propia ni fue asignada por el `teacher`"},
        404: {"description": "Sesión no encontrada"},
    },
)
def run_auto(
    session_id: UUID,
    db: Session = Depends(get_db),
    user: UserProfile = Depends(require_staff),
):
    _ensure_staff_session_access(db, user, session_id)
    ev = run_auto_evaluation(db, session_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Sesion no encontrada")
    return _serialize_evaluation(db, ev)


@router.get(
    "/{session_id}",
    response_model=EvaluationResponse,
    summary="Obtener evaluación de sesión",
    description=(
        "Devuelve la evaluación completa de una sesión. "
        "Si aún no existe, puede generarse automáticamente con métricas base.\n\n"
        "Solo el dueño de la sesión, `admin` (cualquiera) o el `teacher` que la asignó."
    ),
    response_description="Evaluación de la sesión con métricas automáticas y scores de rúbrica.",
    responses={
        401: {"description": "Token no enviado o inválido"},
        403: {"description": "El usuario no es dueño de la sesión, ni admin, ni el `teacher` que la asignó"},
        404: {"description": "Sesión no encontrada"},
    },
)
def get_evaluation(
    session_id: UUID,
    db: Session = Depends(get_db),
    payload: dict = Depends(verify_supabase_jwt),
):
    ev = EvaluationsRepository.get_by_session(db, session_id)
    session = SessionRepository.get_by_id(db, session_id)

    if ev is None and session is None:
        raise HTTPException(status_code=404, detail="Sesion no encontrada")

    user_id = get_subject_id(payload)
    owner_id = ev.student_id if ev is not None else getattr(session, "user_id", None)
    if owner_id != user_id:
        role = get_user_role(db, user_id)
        # Sin sesión (evaluación huérfana) no se puede comprobar quién la asignó: solo admin.
        allowed = role == "admin" if session is None else can_access_session(role, user_id, session)
        if not allowed:
            raise HTTPException(
                status_code=403,
                detail="Solo el dueno de la sesion, un admin o el docente que la asigno puede ver esta evaluacion",
            )

    if not ev:
        ev = run_auto_evaluation(db, session_id)
        if not ev:
            logger.warning(
                "[evaluation] No se pudo generar evaluacion automatica para session_id=%s",
                session_id,
            )
            raise HTTPException(status_code=404, detail="Sesion no encontrada")

    return _serialize_evaluation(db, ev)


@router.put(
    "/{session_id}",
    response_model=EvaluationResponse,
    summary="Enviar evaluación del docente",
    description=(
        "Guarda o actualiza la evaluación del docente sobre una sesión, incluyendo puntajes por criterio "
        "y retroalimentación textual.\n\n"
        "Requiere rol `teacher` o `admin`; el `teacher` solo en sesiones propias o que asignó."
    ),
    response_description="Evaluación actualizada con scores y feedback del docente.",
    responses={
        400: {"description": "Status inválido"},
        401: {"description": "Token no enviado o inválido"},
        403: {"description": "Se requiere rol `teacher` o `admin`, o la sesión no es propia ni fue asignada por el `teacher`"},
        404: {"description": "La sesión o la evaluación no existen; ejecutar primero `/auto`"},
    },
)
def submit_teacher_evaluation(
    session_id: UUID,
    body: TeacherEvaluationInput,
    db: Session = Depends(get_db),
    user: UserProfile = Depends(require_staff),
):
    if body.status not in ("draft", "submitted", "reviewed"):
        raise HTTPException(status_code=400, detail="Status invalido")

    _ensure_staff_session_access(db, user, session_id)
    ev = EvaluationsRepository.submit_teacher_evaluation(
        db,
        session_id=session_id,
        evaluator_id=user.id,
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


@router.get(
    "/",
    response_model=list[EvaluationListItemResponse],
    summary="Listar evaluaciones",
    description=(
        "Devuelve la lista de evaluaciones para la vista principal del módulo de evaluación. "
        "Permite filtrar por una o varias sesiones con `session_ids`. "
        "Los estudiantes solo ven sus propias evaluaciones; el `teacher` las de sesiones propias "
        "o que asignó; `admin` ve todas."
    ),
    response_description="Lista de evaluaciones con datos de sesión y estudiante.",
    responses={401: {"description": "Token no enviado o inválido"}},
)
def list_evaluations(
    session_ids: list[UUID] = Query(
        default=[],
        description="Filtrar por una o más sesiones específicas.",
    ),
    db: Session = Depends(get_db),
    payload: dict = Depends(verify_supabase_jwt),
):
    from app.models.profile import Profile
    from app.models.session_evaluation import SessionEvaluation
    from app.models.sessions import Session as SessionModel
    from sqlalchemy import desc
    from sqlalchemy.orm import aliased

    user_id = get_subject_id(payload)

    StudentProfile = aliased(UserProfile)
    AssignedByProfile = aliased(UserProfile)

    q = (
        db.query(SessionEvaluation, SessionModel, Profile, StudentProfile, AssignedByProfile)
        .outerjoin(SessionModel, SessionModel.id == SessionEvaluation.session_id)
        .outerjoin(Profile, Profile.id == SessionModel.profile_id)
        .outerjoin(StudentProfile, StudentProfile.id == SessionEvaluation.student_id)
        .outerjoin(AssignedByProfile, AssignedByProfile.id == SessionModel.assigned_by)
        .order_by(desc(SessionEvaluation.created_at))
    )

    visibility = _evaluation_visibility_filter(get_user_role(db, user_id), user_id)
    if visibility is not None:
        q = q.filter(visibility)

    if session_ids:
        q = q.filter(SessionEvaluation.session_id.in_(session_ids))

    rows = q.limit(200).all()
    out = []
    for (e, s, p_row, student_row, assigned_by_row) in rows:
        out.append({
            "id": str(e.id),
            "session_id": str(e.session_id),
            "student_id": str(e.student_id) if e.student_id else None,
            "student_name": student_row.full_name if student_row else None,
            "assigned_by_id": str(s.assigned_by) if s and s.assigned_by else None,
            "assigned_by_name": assigned_by_row.full_name if assigned_by_row else None,
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


@router.get(
    "/student/{student_id}",
    response_model=list[StudentEvaluationHistoryItemResponse],
    summary="Historial de evaluaciones de un estudiante",
    description=(
        "Devuelve el historial de evaluaciones de un estudiante específico. "
        "Los estudiantes solo pueden consultar su propio historial. El `teacher` ve de otro estudiante "
        "únicamente las evaluaciones de las sesiones que asignó; `admin` ve todas.\n\n"
        "Requiere ser el propio estudiante o tener rol `teacher` o `admin`."
    ),
    response_description="Lista de evaluaciones del estudiante con métricas y feedback.",
    responses={
        401: {"description": "Token no enviado o inválido"},
        403: {"description": "El estudiante consulta el historial de otro usuario"},
    },
)
def list_student_evaluations(
    student_id: UUID,
    db: Session = Depends(get_db),
    payload: dict = Depends(verify_supabase_jwt),
):
    user_id = get_subject_id(payload)
    assigned_by = None
    if user_id != student_id:
        role = get_user_role(db, user_id)
        if role == "teacher":
            assigned_by = user_id
        elif role != "admin":
            raise HTTPException(
                status_code=403,
                detail="Solo puedes ver tus propias evaluaciones",
            )

    evs = EvaluationsRepository.list_by_student(db, student_id, assigned_by=assigned_by)
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
