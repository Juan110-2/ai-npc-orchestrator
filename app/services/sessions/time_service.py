"""
Session time tracking service.

Criteria for time_source:
  'none'        → session still active, no consolidated data yet
  'explicit'    → frontend timer sent at least one delta flush
  'estimated'   → backend computed from message gaps at close time
  'unavailable' → session closed without enough evidence to compute time
                  (fewer than 2 messages and no explicit timer)

Rules:
  - explicit always wins; never overwrite explicit data
  - finalize_session_time must be called when a session closes
  - no closed session should remain with time_source='none'
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from app.models.sessions import Session as SessionModel
from app.repositories.conversation_repository import ConversationRepository

_IDLE_CAP_SECONDS = 600  # 10 minutes — same threshold as frontend idle timeout
_STALE_SESSION_HOURS = 24  # sesiones "active" sin actividad por mas de esto se cierran solas


def compute_estimated_seconds(db: DBSession, session_id) -> int:
    """
    Estimate practice time by summing gaps between consecutive messages,
    each capped at _IDLE_CAP_SECONDS to exclude abandon periods.
    Returns 0 if fewer than 2 messages exist.
    """
    msgs = ConversationRepository.list_by_session(db, session_id)
    if len(msgs) < 2:
        return 0
    total = 0
    for i in range(1, len(msgs)):
        gap = (msgs[i].created_at - msgs[i - 1].created_at).total_seconds()
        total += min(gap, _IDLE_CAP_SECONDS)
    return int(total)


def finalize_session_time(db: DBSession, session: SessionModel) -> None:
    """
    Called immediately after a session is closed (ended_at set + committed).
    Guarantees that no closed session stays with time_source='none'.

    If the frontend already sent explicit deltas → do nothing.
    Otherwise → compute estimate from message gaps or mark unavailable.
    """
    if session.time_source == 'explicit':
        return  # explicit data wins — never overwrite

    estimated = compute_estimated_seconds(db, session.id)
    if estimated > 0:
        session.accumulated_seconds = estimated
        session.time_source = 'estimated'
    else:
        session.accumulated_seconds = 0
        session.time_source = 'unavailable'


def auto_close_stale_sessions(db: DBSession, hours: int = _STALE_SESSION_HOURS) -> int:
    """
    Cierra sesiones que quedaron en status='active' sin ninguna actividad
    (ni heartbeat de tiempo, ni mensajes nuevos) por mas de `hours`.

    No existe ningun mecanismo (cron, timeout de servidor) que cierre una
    sesion abandonada -- si alguien cierra la pestana sin terminarla, se
    queda "activa" indefinidamente. Esto ensucia tanto el conteo de
    "sesiones activas" como cualquier calculo que use started_at/ended_at
    de sesiones viejas. Se llama de forma perezosa al listar sesiones, en
    vez de depender de un job programado que este proyecto no tiene.

    `ended_at` se fija en el momento de la ULTIMA actividad real (no en
    "ahora"), para que la sesion cerrada refleje cuando realmente se dejo
    de usar, y para que finalize_session_time calcule un accumulated_seconds
    correcto a partir de los gaps entre mensajes.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    rows = db.execute(text("""
        select s.id,
               greatest(
                   coalesce(s.last_interaction_at, s.started_at),
                   coalesce(
                       (select max(cm.created_at) from public.conversation_messages cm
                        where cm.session_id = s.id),
                       s.started_at
                   )
               ) as last_activity
        from public.sessions s
        where s.status = 'active' and s.ended_at is null
    """)).mappings().all()

    closed = 0
    for row in rows:
        last_activity = row["last_activity"]
        if last_activity is None or last_activity >= cutoff:
            continue
        session = db.query(SessionModel).filter(SessionModel.id == row["id"]).first()
        if not session or session.ended_at:
            continue
        session.ended_at = last_activity
        session.status = "completed"
        finalize_session_time(db, session)
        closed += 1

    if closed:
        db.commit()
    return closed
