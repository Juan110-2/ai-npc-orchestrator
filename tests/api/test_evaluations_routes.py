import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.api.v1.routes import evaluations as evaluations_routes
from tests.api.test_utils import build_client, clear_overrides, make_evaluation, make_session, make_user


class TestEvaluationRoutes(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.client = build_client(self.db)

    def tearDown(self):
        clear_overrides()

    @patch("app.api.v1.routes.evaluations.RubricsRepository.get_active")
    def test_get_active_rubric_returns_public_payload(self, mock_get_active):
        rubric = SimpleNamespace(
            id=uuid4(),
            version=1,
            name="Rubrica",
            description="Desc",
            criteria=[{"key": "empathy", "label": "Empathy", "weight": 1, "max_score": 5}],
            is_active=True,
        )
        mock_get_active.return_value = rubric

        response = self.client.get("/evaluation/rubric/active")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["name"], "Rubrica")
        self.assertTrue(body["is_active"])

    @patch.object(evaluations_routes, "SUPABASE_JWT_SECRET", None)
    @patch("app.api.v1.routes.evaluations.run_auto_evaluation")
    @patch("app.api.v1.routes.evaluations.SessionRepository.get_by_id")
    @patch("app.api.v1.routes.evaluations.EvaluationsRepository.get_by_session")
    def test_get_evaluation_autocreates_when_missing(
        self,
        mock_get_by_session,
        mock_get_session,
        mock_run_auto,
    ):
        session = make_session()
        evaluation = make_evaluation(session_id=session.id, student_id=session.user_id)
        mock_get_by_session.return_value = None
        mock_get_session.return_value = session
        mock_run_auto.return_value = evaluation

        response = self.client.get(f"/evaluation/{session.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session_id"], str(session.id))

    @patch("app.api.v1.routes.evaluations.run_auto_evaluation")
    def test_run_auto_requires_staff_dependency(self, mock_run_auto):
        evaluation = make_evaluation()
        mock_run_auto.return_value = evaluation
        self.client.app.dependency_overrides[evaluations_routes._require_staff_or_dev] = (
            lambda: make_user(role="teacher")
        )

        response = self.client.post(f"/evaluation/{evaluation.session_id}/auto")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(evaluation.id))

    @patch("app.api.v1.routes.evaluations.EvaluationsRepository.submit_teacher_evaluation")
    def test_submit_teacher_evaluation_returns_404_when_missing(self, mock_submit):
        mock_submit.return_value = None
        self.client.app.dependency_overrides[evaluations_routes._require_staff_or_dev] = (
            lambda: make_user(role="teacher")
        )
        session_id = uuid4()

        response = self.client.put(
            f"/evaluation/{session_id}",
            json={"scores": {}, "teacher_feedback": "ok", "status": "submitted"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn("Ejecuta primero", response.json()["detail"])
