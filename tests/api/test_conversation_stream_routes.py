import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.conversation.models import StreamInputs, TurnContext
from tests.api.test_utils import build_client, clear_overrides, make_session, override_session_access


class _ResponseMode:
    value = "supportive"


def _make_ctx(**overrides):
    decision = SimpleNamespace(
        response_mode=_ResponseMode(),
        max_sentences=2,
        should_rotate_focus=False,
    )
    data = {
        "decision": decision,
        "forced_close": False,
        "closing": None,
        "should_close": False,
        "closing_kind": None,
        "context_history": [],
        "final_severity": 2.5,
        "b_min": 0.0,
        "b_max": 5.0,
        "behavioral_flags": (),
    }
    data.update(overrides)
    return TurnContext(**data)


class TestConversationStreamRoutes(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.client = build_client(self.db)

    def tearDown(self):
        clear_overrides()

    @patch("app.services.conversation.streaming.finalize_and_evaluate_stream")
    @patch("app.services.conversation.streaming.commit_stream_message", return_value=True)
    @patch("app.services.conversation.streaming.SessionLocal")
    @patch("app.api.v1.routes.conversation.build_stream_inputs")
    @patch("app.api.v1.routes.conversation.process_turn")
    @patch("app.api.v1.routes.conversation.resolve_session_context")
    def test_converse_stream_returns_sse_done_sequence(
        self,
        mock_resolve,
        mock_process_turn,
        mock_build_stream_inputs,
        mock_session_local,
        _mock_commit,
        mock_finalize,
    ):
        session = make_session()
        override_session_access(session)
        mock_resolve.return_value = (session, SimpleNamespace(), SimpleNamespace())
        mock_process_turn.return_value = _make_ctx(should_close=True, closing_kind="resolution")
        mock_build_stream_inputs.return_value = StreamInputs(
            system_prompt=None,
            effective_user_input="hola",
            forced_text="hola mundo",
        )
        mock_session_local.return_value = MagicMock()

        with self.client.stream(
            "POST",
            f"/conversation/{session.id}/stream",
            json={"content": "hola"},
        ) as response:
            body = "".join(response.iter_text())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        self.assertIn("event: chunk", body)
        self.assertIn("event: done", body)

        done_raw = body.split("event: done\ndata: ", 1)[1].split("\n\n", 1)[0]
        done_payload = json.loads(done_raw)
        self.assertTrue(done_payload["done"])
        self.assertEqual(done_payload["closing_kind"], "resolution")
        self.assertEqual(done_payload["metrics"]["provider"], "deterministic")
        mock_finalize.assert_called_once()

    @patch("app.services.conversation.streaming.discard_failed_turn")
    @patch("app.services.conversation.streaming.commit_stream_message")
    @patch("app.services.conversation.streaming.SessionLocal")
    @patch("app.api.v1.routes.conversation.build_stream_inputs")
    @patch("app.api.v1.routes.conversation.process_turn")
    @patch("app.api.v1.routes.conversation.resolve_session_context")
    def test_converse_stream_returns_error_event_when_provider_fails(
        self,
        mock_resolve,
        mock_process_turn,
        mock_build_stream_inputs,
        mock_session_local,
        mock_commit,
        mock_discard_turn,
    ):
        session = make_session()
        override_session_access(session)
        mock_resolve.return_value = (session, SimpleNamespace(), SimpleNamespace())
        mock_process_turn.return_value = _make_ctx()
        mock_build_stream_inputs.return_value = StreamInputs(
            system_prompt="prompt",
            effective_user_input="hola",
            forced_text=None,
        )
        mock_session_local.return_value = MagicMock()
        mock_commit.return_value = True
        mock_discard_turn.return_value = True
        expected_error = RuntimeError("provider down")

        def fake_iter_ai_stream(*, state, **_kwargs):
            state.accumulated = "parcial"
            state.stream_error = expected_error
            yield 'event: chunk\ndata: {"chunk": "parcial"}\n\n'

        with patch("app.services.conversation.streaming.iter_ai_stream", fake_iter_ai_stream):
            with self.client.stream(
                "POST",
                f"/conversation/{session.id}/stream",
                json={"content": "hola"},
            ) as response:
                body = "".join(response.iter_text())

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: error", body)
        error_raw = body.split("event: error\ndata: ", 1)[1].split("\n\n", 1)[0]
        self.assertIs(json.loads(error_raw)["discarded"], True)
        mock_discard_turn.assert_called_once()
        mock_commit.assert_not_called()

    @patch("app.services.conversation.streaming.discard_failed_turn", return_value=True)
    @patch("app.services.conversation.streaming.finalize_and_evaluate_stream")
    @patch("app.services.conversation.streaming.commit_stream_message", return_value=False)
    @patch("app.services.conversation.streaming.SessionLocal")
    @patch("app.api.v1.routes.conversation.build_stream_inputs")
    @patch("app.api.v1.routes.conversation.process_turn")
    @patch("app.api.v1.routes.conversation.resolve_session_context")
    def test_converse_stream_returns_error_event_when_commit_fails(
        self,
        mock_resolve,
        mock_process_turn,
        mock_build_stream_inputs,
        mock_session_local,
        _mock_commit,
        mock_finalize,
        _mock_discard_turn,
    ):
        session = make_session()
        override_session_access(session)
        mock_resolve.return_value = (session, SimpleNamespace(), SimpleNamespace())
        mock_process_turn.return_value = _make_ctx()
        mock_build_stream_inputs.return_value = StreamInputs(
            system_prompt=None,
            effective_user_input="hola",
            forced_text="respuesta corta",
        )
        mock_session_local.return_value = MagicMock()

        with self.client.stream(
            "POST",
            f"/conversation/{session.id}/stream",
            json={"content": "hola"},
        ) as response:
            body = "".join(response.iter_text())

        self.assertEqual(response.status_code, 200)
        error_raw = body.split("event: error\ndata: ", 1)[1].split("\n\n", 1)[0]
        self.assertIs(json.loads(error_raw)["discarded"], True)
        self.assertNotIn("event: done", body)
        mock_finalize.assert_not_called()

    @patch("app.services.conversation.streaming.discard_failed_turn", return_value=False)
    @patch("app.services.conversation.streaming.commit_stream_message", return_value=False)
    @patch("app.services.conversation.streaming.SessionLocal")
    @patch("app.api.v1.routes.conversation.build_stream_inputs")
    @patch("app.api.v1.routes.conversation.process_turn")
    @patch("app.api.v1.routes.conversation.resolve_session_context")
    def test_converse_stream_error_event_reports_discarded_false_when_rollback_fails(
        self,
        mock_resolve,
        mock_process_turn,
        mock_build_stream_inputs,
        mock_session_local,
        _mock_commit,
        _mock_discard_turn,
    ):
        session = make_session()
        override_session_access(session)
        mock_resolve.return_value = (session, SimpleNamespace(), SimpleNamespace())
        mock_process_turn.return_value = _make_ctx()
        mock_build_stream_inputs.return_value = StreamInputs(
            system_prompt=None,
            effective_user_input="hola",
            forced_text="respuesta corta",
        )
        mock_session_local.return_value = MagicMock()

        with self.client.stream(
            "POST",
            f"/conversation/{session.id}/stream",
            json={"content": "hola"},
        ) as response:
            body = "".join(response.iter_text())

        error_raw = body.split("event: error\ndata: ", 1)[1].split("\n\n", 1)[0]
        payload = json.loads(error_raw)
        self.assertIs(payload["discarded"], False)
        self.assertIn("Recarga la conversación", payload["error"])
        self.assertNotIn("event: done", body)
