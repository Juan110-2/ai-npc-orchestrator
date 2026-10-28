import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.api.v1.deps import require_staff
from tests.api.test_utils import (
    build_client,
    clear_overrides,
    make_evaluation,
    make_session,
    make_user,
    override_auth,
)


class TestEvaluationRoutes(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.client = build_client(self.db)
        override_auth()

    def tearDown(self):
        clear_overrides()

    @patch("app.api.v1.routes.evaluations.RubricsRepository.get_active")
    def test_get_active_rubric_returns_payload(self, mock_get_active):
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

    @patch("app.api.v1.routes.evaluations.RubricsRepository.get_active")
    def test_get_active_rubric_matches_real_database_shape(self, mock_get_active):
        """
        RubricDefinition (app/models/rubric_definition.py) declara:
          version  = Column(Integer, ...)   -> un entero, no un string
          criteria = Column(JSONB, ...)     -> un arreglo de dicts, no un dict

        Este test simula exactamente esa forma (la que Postgres realmente
        devuelve), no la forma que asumia el schema de respuesta viejo.
        Diagnostico de "no cargan las evaluaciones": DIAGNOSTICO.md
        """
        rubric = SimpleNamespace(
            id=uuid4(),
            version=1,
            name="Rubrica",
            description="Desc",
            criteria=[
                {"key": "empatia", "label": "Empatia", "weight": 0.5, "max_score": 5},
                {"key": "claridad", "label": "Claridad", "weight": 0.5, "max_score": 5},
            ],
            is_active=True,
        )
        mock_get_active.return_value = rubric

        response = self.client.get("/evaluation/rubric/active")

        self.assertEqual(
            response.status_code,
            200,
            f"GET /evaluation/rubric/active fallo con datos reales (version=int, "
            f"criteria=list). Body: {response.text}",
        )

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
        override_auth(session.user_id)
        evaluation = make_evaluation(session_id=session.id, student_id=session.user_id)
        mock_get_by_session.return_value = None
        mock_get_session.return_value = session
        mock_run_auto.return_value = evaluation

        response = self.client.get(f"/evaluation/{session.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session_id"], str(session.id))

    @patch("app.api.v1.routes.evaluations.SessionRepository.get_by_id")
    @patch("app.api.v1.routes.evaluations.run_auto_evaluation")
    def test_run_auto_requires_staff_dependency(self, mock_run_auto, mock_get_session):
        evaluation = make_evaluation()
        mock_run_auto.return_value = evaluation
        teacher = make_user(role="teacher")
        mock_get_session.return_value = make_session(id=evaluation.session_id, assigned_by=teacher.id)
        self.client.app.dependency_overrides[require_staff] = lambda: teacher

        response = self.client.post(f"/evaluation/{evaluation.session_id}/auto")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(evaluation.id))

    @patch("app.api.v1.routes.evaluations.SessionRepository.get_by_id")
    @patch("app.api.v1.routes.evaluations.EvaluationsRepository.submit_teacher_evaluation")
    def test_submit_teacher_evaluation_returns_404_when_missing(self, mock_submit, mock_get_session):
        mock_submit.return_value = None
        teacher = make_user(role="teacher")
        session_id = uuid4()
        mock_get_session.return_value = make_session(id=session_id, assigned_by=teacher.id)
        self.client.app.dependency_overrides[require_staff] = lambda: teacher

        response = self.client.put(
            f"/evaluation/{session_id}",
            json={"scores": {}, "teacher_feedback": "ok", "status": "submitted"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn("Ejecuta primero", response.json()["detail"])


_EV = "app.api.v1.routes.evaluations"


class TestEvaluationDraftVisibility(unittest.TestCase):
    """El estudiante no ve la calificación del docente mientras la evaluación está en borrador."""

    def setUp(self):
        self.db = MagicMock()
        self.client = build_client(self.db)
        self.student_id = uuid4()
        self.teacher_id = uuid4()
        self.session = make_session(user_id=self.student_id, assigned_by=self.teacher_id)
        self.scores = {"escucha_activa": 4.5}
        self.feedback = "Buena validación emocional."

    def tearDown(self):
        clear_overrides()

    def _evaluation(self, status):
        return make_evaluation(
            session_id=self.session.id,
            student_id=self.student_id,
            status=status,
            scores=dict(self.scores),
            teacher_feedback=self.feedback,
        )

    def _as(self, role, user_id):
        override_auth(user_id)
        patcher = patch(f"{_EV}.get_user_role", return_value=role)
        patcher.start()
        self.addCleanup(patcher.stop)

    # GET /evaluation/{session_id}

    def _get_one(self, ev):
        with patch(f"{_EV}.EvaluationsRepository.get_by_session", return_value=ev), patch(
            f"{_EV}.SessionRepository.get_by_id", return_value=self.session
        ), patch(f"{_EV}.RubricsRepository.get_by_id", return_value=None):
            return self.client.get(f"/evaluation/{self.session.id}")

    def test_get_student_draft_hides_scores_and_feedback(self):
        self._as("student", self.student_id)
        response = self._get_one(self._evaluation("draft"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["scores"], {})
        self.assertIsNone(body["teacher_feedback"])
        self.assertIsNone(body["overall_score"])
        self.assertEqual(body["status"], "draft")
        self.assertEqual(body["automatic_metrics"], {"turns_total": 3})

    def test_get_student_submitted_sees_everything(self):
        self._as("student", self.student_id)
        response = self._get_one(self._evaluation("submitted"))
        body = response.json()
        self.assertEqual(body["scores"], self.scores)
        self.assertEqual(body["teacher_feedback"], self.feedback)

    def test_get_staff_draft_sees_everything(self):
        for role, user_id in (("admin", uuid4()), ("teacher", self.teacher_id)):
            with self.subTest(role=role):
                self._as(role, user_id)
                body = self._get_one(self._evaluation("draft")).json()
                self.assertEqual(body["scores"], self.scores)
                self.assertEqual(body["teacher_feedback"], self.feedback)

    # GET /evaluation/ (lista)

    def _list(self, evaluation):
        row = (evaluation, self.session, None, None, None)
        query = self.db.query.return_value
        query.outerjoin.return_value = query
        query.order_by.return_value = query
        query.filter.return_value = query
        query.limit.return_value.all.return_value = [row]
        return self.client.get("/evaluation/")

    def test_list_student_draft_hides_scores(self):
        self._as("student", self.student_id)
        item = self._list(self._evaluation("draft")).json()[0]
        self.assertEqual(item["scores"], {})
        self.assertEqual(item["status"], "draft")

    def test_list_student_submitted_sees_scores(self):
        self._as("student", self.student_id)
        item = self._list(self._evaluation("submitted")).json()[0]
        self.assertEqual(item["scores"], self.scores)

    def test_list_staff_draft_sees_scores(self):
        self._as("teacher", self.teacher_id)
        item = self._list(self._evaluation("draft")).json()[0]
        self.assertEqual(item["scores"], self.scores)

    # GET /evaluation/student/{student_id}

    def _history(self, evaluation):
        with patch(f"{_EV}.EvaluationsRepository.list_by_student", return_value=[evaluation]):
            return self.client.get(f"/evaluation/student/{self.student_id}")

    def test_history_student_draft_hides_scores_and_feedback(self):
        self._as("student", self.student_id)
        item = self._history(self._evaluation("draft")).json()[0]
        self.assertEqual(item["scores"], {})
        self.assertIsNone(item["teacher_feedback"])
        self.assertEqual(item["status"], "draft")

    def test_history_student_submitted_sees_everything(self):
        self._as("student", self.student_id)
        item = self._history(self._evaluation("submitted")).json()[0]
        self.assertEqual(item["scores"], self.scores)
        self.assertEqual(item["teacher_feedback"], self.feedback)

    def test_history_staff_draft_sees_everything(self):
        for role, user_id in (("admin", uuid4()), ("teacher", self.teacher_id)):
            with self.subTest(role=role):
                self._as(role, user_id)
                item = self._history(self._evaluation("draft")).json()[0]
                self.assertEqual(item["scores"], self.scores)
                self.assertEqual(item["teacher_feedback"], self.feedback)
