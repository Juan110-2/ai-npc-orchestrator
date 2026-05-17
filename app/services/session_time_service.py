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

from sqlalchemy.orm import Session as DBSession

from app.models.sessions import Session as SessionModel
from app.repositories.conversation_repository import ConversationRepository

_IDLE_CAP_SECONDS = 600  # 10 minutes — same threshold as frontend idle timeout


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
