"""
Servicio que calcula las metricas automaticas pedagogicas al cerrar una sesion.

IMPORTANTE: estas metricas son INDEPENDIENTES de ai_call_logs.
- ai_call_logs mide proveedor de IA (Cap 3).
- evaluation_service mide la PARTICIPACION DEL ESTUDIANTE (Cap 5).

Las metricas son una sintesis cuantitativa de la conversacion del estudiante:
turnos, categorias detectadas por el clasificador, picos de severidad, etc.
El docente las usa como apoyo para puntuar la rubrica, pero la valoracion
final es manual.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.repositories.evaluations_repository import EvaluationsRepository, RubricsRepository
from app.repositories.sessions_repository import SessionRepository


def compute_automatic_metrics(db: Session, session_id: UUID) -> dict:
    """
    Calcula metricas de la sesion a partir de los turnos almacenados.
    No hace llamadas a IA; usa lo que el clasificador y heuristicas ya dejaron
    en conversation_messages + sessions.
    """
    # Totales y duracion
    base = db.execute(text("""
        select
            s.started_at,
            s.ended_at,
            s.accumulated_seconds,
            s.time_source,
            s.current_severity as severity_final,
            count(cm.id) filter (where cm.role = 'trainee')   as turns_trainee,
            count(cm.id) filter (where cm.role = 'patient')   as turns_patient,
            count(cm.id)                                       as turns_total,
            max(cm.severity)                                   as severity_peak
        from public.sessions s
        left join public.conversation_messages cm on cm.session_id = s.id
        where s.id = :sid
        group by s.id, s.started_at, s.ended_at, s.accumulated_seconds,
                 s.time_source, s.current_severity
    """), {"sid": str(session_id)}).mappings().first()

    if not base:
        return {}

    accumulated_seconds = int(base["accumulated_seconds"] or 0)
    time_source = base["time_source"] or "none"

    duration_minutes: Optional[float] = None
    if time_source in ("explicit", "estimated") and accumulated_seconds > 0:
        # Tiempo de práctica efectiva reportado por el frontend o estimado por gaps
        duration_minutes = accumulated_seconds / 60.0
    elif base["started_at"] and base["ended_at"]:
        # Fallback para sesiones sin datos de tiempo (legacy / clientes sin timer)
        duration_minutes = (
            (base["ended_at"] - base["started_at"]).total_seconds() / 60.0
        )

    # Estados tecnicos del clasificador (ok, parse_error, etc.).
    status_rows = db.execute(text("""
        select status, count(*)::int as n
        from public.ai_call_logs
        where session_id = :sid and purpose = 'classifier'
        group by status
    """), {"sid": str(session_id)}).mappings().all()
    classifier_calls_by_status = {r["status"]: r["n"] for r in status_rows}

    # Categorias reales del clasificador (si el log las tiene).
    classifier_calls_by_category: dict[str, int] = {}
    try:
        category_rows = db.execute(text("""
            select category, count(*)::int as n
            from public.ai_call_logs
            where session_id = :sid
              and purpose = 'classifier'
              and category is not null
            group by category
        """), {"sid": str(session_id)}).mappings().all()
        classifier_calls_by_category = {r["category"]: r["n"] for r in category_rows}
    except Exception:
        classifier_calls_by_category = {}

    # Turnos del NPC cuyo contenido fue clasificado como RIESGO real
    # (ideacion, dano, etc.), leyendo el risk_flags que persiste cada turno.
    # OJO: esto NO es lo mismo que "severidad alta" -- un caso de crisis puede
    # tener severidad >=4 en todos sus turnos sin que haya riesgo real en ellos.
    risk_alerts = db.execute(text("""
        select count(*)::int as n
        from public.conversation_messages
        where session_id = :sid
          and role = 'patient'
          and risk_flags @> '["risk"]'::jsonb
    """), {"sid": str(session_id)}).mappings().one()["n"]

    last_model_row = db.execute(text("""
        select ai_model
        from public.conversation_messages
        where session_id = :sid
          and role = 'patient'
          and ai_model is not null
        order by created_at desc
        limit 1
    """), {"sid": str(session_id)}).mappings().first()

    return {
        "turns_total": int(base["turns_total"] or 0),
        "turns_trainee": int(base["turns_trainee"] or 0),
        "turns_patient": int(base["turns_patient"] or 0),
        "duration_minutes": (
            round(duration_minutes, 2) if duration_minutes is not None else None
        ),
        "duration_source": time_source,
        "severity_peak": round(float(base["severity_peak"]), 1) if base["severity_peak"] is not None else None,
        "severity_final": round(float(base["severity_final"]), 1) if base["severity_final"] is not None else None,
        "risk_alerts_detected": int(risk_alerts or 0),
        "last_ai_model": last_model_row["ai_model"] if last_model_row else None,
        "classifier_calls_by_status": classifier_calls_by_status,
        "classifier_calls_by_category": classifier_calls_by_category,
    }


def compute_overall_score(scores: dict, criteria: list) -> Optional[float]:
    """
    Calcula el puntaje ponderado total a partir de los scores del docente
    y los pesos definidos en la rubrica. Retorna un valor entre 0 y 5.
    """
    if not scores or not criteria:
        return None
    total = 0.0
    used_weight = 0.0
    for c in criteria:
        key = c.get("key")
        weight = float(c.get("weight", 0))
        max_score = float(c.get("max_score", 5))
        if key in scores and weight > 0 and max_score > 0:
            val = float(scores[key])
            # normalizamos a escala 0..5
            normalized = max(0.0, min(max_score, val)) / max_score * 5.0
            total += normalized * weight
            used_weight += weight
    if used_weight == 0:
        return None
    return round(total / used_weight, 2)


def run_auto_evaluation(db: Session, session_id: UUID):
    """
    Pipeline completo: leer sesion, calcular metricas y upsertar en
    session_evaluations. Idempotente.
    """
    session = SessionRepository.get_by_id(db, session_id)
    if not session:
        return None

    rubric = RubricsRepository.get_active(db)
    metrics = compute_automatic_metrics(db, session_id)

    ev = EvaluationsRepository.upsert_automatic_metrics(
        db,
        session_id=session_id,
        student_id=getattr(session, "user_id", None),
        evaluator_id=getattr(session, "assigned_by", None),
        rubric_id=rubric.id if rubric else None,
        automatic_metrics=metrics,
    )
    return ev
