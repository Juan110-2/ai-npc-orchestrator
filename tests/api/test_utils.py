from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.v1.deps import get_db
from app.main import app


def build_client(db_override):
    app.dependency_overrides[get_db] = lambda: db_override
    return TestClient(app)


def clear_overrides():
    app.dependency_overrides.clear()


def make_session(**overrides):
    now = datetime.now(timezone.utc)
    data = {
        "id": uuid4(),
        "profile_id": uuid4(),
        "scenario_id": uuid4(),
        "user_id": uuid4(),
        "assigned_by": uuid4(),
        "assigned_at": now,
        "status": "active",
        "accumulated_seconds": 0,
        "time_source": "none",
        "last_interaction_at": now,
        "current_severity": 3.0,
        "base_severity": 3.0,
        "started_at": now,
        "ended_at": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def make_user(**overrides):
    now = datetime.now(timezone.utc)
    data = {
        "id": uuid4(),
        "email": "test@example.com",
        "full_name": "Test User",
        "role": "student",
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def make_evaluation(**overrides):
    now = datetime.now(timezone.utc)
    data = {
        "id": uuid4(),
        "session_id": uuid4(),
        "student_id": uuid4(),
        "evaluator_id": uuid4(),
        "rubric_id": uuid4(),
        "status": "draft",
        "automatic_metrics": {"turns_total": 3},
        "scores": {},
        "teacher_feedback": None,
        "created_at": now,
        "updated_at": now,
        "submitted_at": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def override_auth(user_id=None):
    """Simula un JWT válido (`verify_supabase_jwt`) para el usuario indicado."""
    from app.core.auth import verify_supabase_jwt

    sub = str(user_id or uuid4())
    app.dependency_overrides[verify_supabase_jwt] = lambda: {"sub": sub}


def override_session_access(session):
    """Omite la autorización por sesión, para probar solo la lógica de la ruta."""
    from app.api.v1.deps import require_session_access, require_session_owner

    app.dependency_overrides[require_session_access] = lambda: session
    app.dependency_overrides[require_session_owner] = lambda: session


def make_message(**overrides):
    now = datetime.now(timezone.utc)
    data = {
        "id": uuid4(),
        "session_id": uuid4(),
        "role": "patient",
        "content": "Respuesta",
        "severity": 2.5,
        "risk_flags": [],
        "ai_provider": "mock",
        "tokens_used": 42,
        "created_at": now,
    }
    data.update(overrides)
    return SimpleNamespace(**data)
