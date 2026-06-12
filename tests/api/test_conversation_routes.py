import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from tests.api.test_utils import (
    build_client,
    clear_overrides,
    make_message,
    make_session,
)


class TestConversationRoutes(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.client = build_client(self.db)

    def tearDown(self):
        clear_overrides()

    @patch("app.api.v1.routes.conversation.finalize_and_evaluate_sync")
    @patch("app.api.v1.routes.conversation.commit_patient_message")
    @patch("app.api.v1.routes.conversation.persist_patient_message")
    @patch("app.api.v1.routes.conversation.generate_sync_ai_response")
    @patch("app.api.v1.routes.conversation.process_turn")
    @patch("app.api.v1.routes.conversation.resolve_session_context")
    def test_converse_returns_patient_message(
        self,
        mock_resolve,
        mock_process_turn,
        mock_generate,
        mock_persist,
        mock_commit,
        mock_finalize,
    ):
        session = make_session()
        profile = SimpleNamespace()
        scenario = SimpleNamespace()
        patient_message = make_message(session_id=session.id)
        ai_response = SimpleNamespace(
            content="Hola",
            provider="mock",
            model="test-model",
            tokens_input=10,
            tokens_output=12,
            tokens_total=22,
            latency_ms=15.0,
        )

        mock_resolve.return_value = (session, profile, scenario)
        mock_process_turn.return_value = SimpleNamespace()
        mock_generate.return_value = ai_response
        mock_persist.return_value = patient_message

        response = self.client.post(
            f"/conversation/{session.id}",
            json={"content": "Hola"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(patient_message.id))
        mock_commit.assert_called_once_with(self.db, session.id)
        mock_finalize.assert_called_once()

    @patch("app.api.v1.routes.conversation.resolve_session_context")
    def test_converse_rejects_blank_content(self, mock_resolve):
        session = make_session()
        mock_resolve.return_value = (session, SimpleNamespace(), SimpleNamespace())

        response = self.client.post(
            f"/conversation/{session.id}",
            json={"content": "   "},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Missing content")

    @patch("app.api.v1.routes.conversation.ConversationRepository.list_by_session")
    @patch("app.api.v1.routes.conversation.SessionRepository.get_by_id")
    def test_get_history_returns_messages(self, mock_get_session, mock_list):
        session = make_session()
        message = make_message(session_id=session.id)
        mock_get_session.return_value = session
        mock_list.return_value = [message]

        response = self.client.get(f"/conversation/{session.id}/history")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["content"], message.content)

    @patch("app.api.v1.routes.conversation.SessionRepository.get_by_id")
    def test_get_history_returns_404_when_session_is_missing(self, mock_get_session):
        mock_get_session.return_value = None

        response = self.client.get(f"/conversation/{uuid4()}/history")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Session not found")
