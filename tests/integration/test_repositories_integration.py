import socket
import unittest
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import uuid4

import pytest

from app.core.config import DATABASE_URL
from app.core.database import SessionLocal
from app.models.conversation_message import ConversationMessage
from app.models.profile import Profile
from app.models.scenario import Scenario
from app.models.session_evaluation import SessionEvaluation
from app.models.sessions import Session as SessionModel
from app.models.user_profile import UserProfile
from app.repositories.evaluations_repository import EvaluationsRepository
from app.repositories.profile_repository import ProfileRepository
from app.repositories.scenario_repository import ScenarioRepository
from app.repositories.sessions_repository import SessionRepository
from app.schemas.profile import ProfileCreate, ProfileUpdate
from app.schemas.scenario import ScenarioCreate, ScenarioUpdate


def _database_reachable(database_url: str | None, timeout: float = 2.0) -> bool:
    """Prueba una conexión TCP rápida a la base de datos, sin resolver DNS ni
    conectar de más si no hay red disponible (evita colgar pytest en CI/offline)."""
    if not database_url:
        return False

    parsed = urlparse(database_url)
    if not parsed.hostname:
        return False

    try:
        with socket.create_connection((parsed.hostname, parsed.port or 5432), timeout=timeout):
            return True
    except OSError:
        return False


_DATABASE_AVAILABLE = _database_reachable(DATABASE_URL)


@pytest.mark.skipif(
    not _DATABASE_AVAILABLE,
    reason="DATABASE_URL no está definido o la base de datos no es alcanzable en este entorno",
)
class TestRepositoriesIntegration(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        self.profile_ids: list = []
        self.scenario_ids: list = []
        self.session_ids: list = []

    def tearDown(self):
        self.db.rollback()

        if self.session_ids:
            self.db.query(SessionEvaluation).filter(
                SessionEvaluation.session_id.in_(self.session_ids)
            ).delete(synchronize_session=False)
            self.db.query(ConversationMessage).filter(
                ConversationMessage.session_id.in_(self.session_ids)
            ).delete(synchronize_session=False)
            self.db.query(SessionModel).filter(
                SessionModel.id.in_(self.session_ids)
            ).delete(synchronize_session=False)

        if self.profile_ids:
            self.db.query(Profile).filter(Profile.id.in_(self.profile_ids)).delete(
                synchronize_session=False
            )

        if self.scenario_ids:
            self.db.query(Scenario).filter(Scenario.id.in_(self.scenario_ids)).delete(
                synchronize_session=False
            )

        self.db.commit()
        self.db.close()

    def _get_existing_user(self, role: str):
        user = self.db.query(UserProfile).filter(UserProfile.role == role).first()
        if user is None:
            user = self.db.query(UserProfile).first()
        self.assertIsNotNone(user, "La base de datos no tiene registros en public.user_profiles")
        return user

    def _create_profile(self):
        suffix = uuid4().hex[:8]
        profile = ProfileRepository.create(
            self.db,
            ProfileCreate(
                name=f"IT Perfil {suffix}",
                description="Perfil de prueba para integración real.",
                traits={"age": 29, "communication_style": "reservado"},
                behavior={
                    "behavior_min": 1.5,
                    "behavior_max": 2.5,
                    "triggers": ["presión"],
                    "regulators": ["escucha activa"],
                },
            ),
        )
        self.profile_ids.append(profile.id)
        return profile

    def _create_scenario(self):
        suffix = uuid4().hex[:8]
        scenario = ScenarioRepository.create(
            self.db,
            ScenarioCreate(
                name=f"IT Escenario {suffix}",
                context="Escenario de prueba con estrés académico sostenido.",
                severity=5,
                risk_flags=["ansiedad"],
                constraints={"max_turns_before_escalation": 6},
            ),
        )
        self.scenario_ids.append(scenario.id)
        return scenario

    def _create_session(self):
        profile = self._create_profile()
        scenario = self._create_scenario()
        session = SessionRepository.start(
            self.db,
            profile_id=profile.id,
            scenario=scenario,
            profile=profile,
            user_id=None,
            assigned_by=None,
        )
        self.session_ids.append(session.id)
        return session

    def test_profile_repository_crud_with_real_db(self):
        profile = self._create_profile()

        updated = ProfileRepository.update(
            self.db,
            profile.id,
            ProfileUpdate(
                description="Perfil actualizado en integración.",
                behavior={
                    "behavior_min": 0.5,
                    "behavior_max": 4.0,
                    "triggers": ["juicio"],
                    "regulators": ["validación emocional"],
                },
            ),
        )

        self.assertIsNotNone(updated)
        self.assertEqual(updated.description, "Perfil actualizado en integración.")
        self.assertEqual(updated.behavior["behavior_max"], 4.0)

        deleted = ProfileRepository.delete(self.db, profile.id)
        self.assertTrue(deleted)
        self.profile_ids.remove(profile.id)
        self.assertIsNone(ProfileRepository.get_by_id(self.db, profile.id))

    def test_scenario_repository_crud_with_real_db(self):
        scenario = self._create_scenario()

        updated = ScenarioRepository.update(
            self.db,
            scenario.id,
            ScenarioUpdate(
                severity=2,
                constraints={"forbidden_topics": ["familia"]},
            ),
        )

        self.assertIsNotNone(updated)
        self.assertEqual(updated.severity, 2)
        self.assertEqual(updated.constraints["forbidden_topics"], ["familia"])

        deleted = ScenarioRepository.delete(self.db, scenario.id)
        self.assertTrue(deleted)
        self.scenario_ids.remove(scenario.id)
        self.assertIsNone(ScenarioRepository.get_by_id(self.db, scenario.id))

    def test_session_repository_start_and_time_tracking_with_real_db(self):
        session = self._create_session()

        self.assertEqual(session.current_severity, 2.5)
        self.assertEqual(session.base_severity, 2.5)

        updated = SessionRepository.add_time_delta(self.db, session.id, 45)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.accumulated_seconds, 45)
        self.assertEqual(updated.time_source, "explicit")

        updated.ended_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(updated)

        after_close = SessionRepository.add_time_delta(self.db, session.id, 30)
        self.assertIsNotNone(after_close)
        self.assertEqual(after_close.accumulated_seconds, 45)

    def test_evaluations_repository_upsert_and_submit_with_real_db(self):
        session = self._create_session()
        student = self._get_existing_user("student")
        evaluator = self._get_existing_user("teacher")

        draft = EvaluationsRepository.upsert_automatic_metrics(
            self.db,
            session_id=session.id,
            student_id=student.id,
            evaluator_id=None,
            rubric_id=None,
            automatic_metrics={"turns_total": 7, "rapport_score": 0.72},
        )

        self.assertEqual(draft.status, "draft")
        self.assertEqual(draft.student_id, student.id)
        self.assertEqual(draft.automatic_metrics["turns_total"], 7)

        submitted = EvaluationsRepository.submit_teacher_evaluation(
            self.db,
            session_id=session.id,
            evaluator_id=evaluator.id,
            scores={"empathy": 4, "structure": 5},
            teacher_feedback="Buen manejo del vínculo terapéutico.",
        )

        self.assertIsNotNone(submitted)
        self.assertEqual(submitted.status, "submitted")
        self.assertEqual(submitted.evaluator_id, evaluator.id)
        self.assertEqual(submitted.scores["structure"], 5)
        self.assertIsNotNone(submitted.submitted_at)

        history = EvaluationsRepository.list_by_student(self.db, student.id, limit=10)
        self.assertTrue(any(item.session_id == session.id for item in history))
