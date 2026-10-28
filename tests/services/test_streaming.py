import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services.conversation.models import StreamInputs, TurnContext
from app.services.conversation.streaming import (
    finalize_and_evaluate_stream,
    stream_response_generator,
)


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


def _error_payload(event: str) -> dict:
    assert event.startswith("event: error\ndata: ")
    return json.loads(event.split("data: ", 1)[1])


class TestStreamingConversation(unittest.TestCase):
    @patch("app.services.conversation.streaming.finalize_session_in_generator")
    @patch("app.services.conversation.streaming.run_auto_evaluation_safely")
    def test_finalize_and_evaluate_stream_only_runs_when_should_close(self, mock_auto, mock_finalize):
        db = MagicMock()
        session_id = uuid4()

        finalize_and_evaluate_stream(db, session_id, _make_ctx(should_close=False))
        mock_finalize.assert_not_called()
        mock_auto.assert_not_called()

        finalize_and_evaluate_stream(db, session_id, _make_ctx(should_close=True))
        mock_finalize.assert_called_once_with(db, session_id, unittest.mock.ANY)
        mock_auto.assert_called_once_with(db, session_id, "converse_stream")

    @patch("app.services.conversation.streaming.finalize_and_evaluate_stream")
    @patch("app.services.conversation.streaming.commit_stream_message", return_value=True)
    @patch("app.services.conversation.streaming.SessionLocal")
    def test_stream_response_generator_forced_text_emits_done(
        self,
        mock_session_local,
        _mock_commit,
        mock_finalize,
    ):
        mock_session_local.return_value = MagicMock()
        ctx = _make_ctx(should_close=True, closing_kind="resolution")
        stream_in = StreamInputs(
            system_prompt=None,
            effective_user_input="hola",
            forced_text="hola mundo",
        )

        events = list(
            stream_response_generator(
                session_id=uuid4(),
                stream_in=stream_in,
                context_messages=[],
                ctx=ctx,
            )
        )

        self.assertTrue(events[0].startswith("event: chunk"))
        self.assertEqual(events[-1].splitlines()[0], "event: done")
        done_payload = json.loads(events[-1].split("data: ", 1)[1])
        self.assertTrue(done_payload["done"])
        self.assertEqual(done_payload["closing_kind"], "resolution")
        self.assertEqual(done_payload["metrics"]["provider"], "deterministic")
        mock_finalize.assert_called_once()

    @patch("app.services.conversation.streaming.finalize_session_in_generator")
    @patch("app.services.conversation.streaming.persist_patient_message")
    @patch("app.services.conversation.core.SessionRepository")
    @patch("app.services.conversation.core.ConversationRepository")
    @patch("app.services.conversation.streaming.SessionLocal")
    def test_stream_response_generator_discards_turn_when_provider_fails(
        self,
        mock_session_local,
        mock_conv_repo,
        mock_session_repo,
        mock_persist_patient,
        mock_finalize,
    ):
        gen_db = MagicMock()
        mock_session_local.return_value = gen_db
        session_row = SimpleNamespace(current_severity=3.4, status="active", ended_at=None)
        mock_session_repo.get_by_id.return_value = session_row
        session_id = uuid4()
        trainee_msg_id = uuid4()
        expected_error = RuntimeError("provider down")

        def fake_iter_ai_stream(*, state, **_kwargs):
            state.accumulated = "parcial"
            state.stream_error = expected_error
            yield "event: chunk\ndata: {\"chunk\": \"parcial\"}\n\n"

        with patch("app.services.conversation.streaming.iter_ai_stream", fake_iter_ai_stream):
            events = list(
                stream_response_generator(
                    session_id=session_id,
                    stream_in=StreamInputs(
                        system_prompt="prompt",
                        effective_user_input="hola",
                        forced_text=None,
                    ),
                    context_messages=[],
                    # should_close=True: aunque el turno iba a cerrar, no debe cerrarse
                    ctx=_make_ctx(
                        should_close=True,
                        closing_kind="crisis",
                        final_severity=5.0,
                        trainee_msg_id=trainee_msg_id,
                        previous_severity=2.8,
                    ),
                )
            )

        # El evento error siempre llega, y es el ultimo
        self.assertTrue(events[-1].startswith("event: error"))
        payload = _error_payload(events[-1])
        self.assertIs(payload["discarded"], True)
        self.assertIn("se descarto", payload["error"])
        # Se borra el mensaje trainee del turno y se restaura la severidad previa
        mock_conv_repo.delete_by_id.assert_called_once_with(gen_db, session_id, trainee_msg_id)
        self.assertEqual(session_row.current_severity, 2.8)
        # La sesion no se cierra y no se guarda respuesta del paciente (ni parcial)
        self.assertEqual(session_row.status, "active")
        self.assertIsNone(session_row.ended_at)
        mock_finalize.assert_not_called()
        mock_persist_patient.assert_not_called()
        gen_db.commit.assert_called()

    @patch("app.services.conversation.streaming.finalize_session_in_generator")
    @patch("app.services.conversation.core.SessionRepository")
    @patch("app.services.conversation.core.ConversationRepository")
    @patch("app.services.conversation.streaming.SessionLocal")
    def test_stream_response_generator_emits_error_even_if_rollback_fails(
        self,
        mock_session_local,
        mock_conv_repo,
        _mock_session_repo,
        mock_finalize,
    ):
        gen_db = MagicMock()
        mock_session_local.return_value = gen_db
        mock_conv_repo.delete_by_id.side_effect = RuntimeError("db caida")

        def fake_iter_ai_stream(*, state, **_kwargs):
            state.stream_error = RuntimeError("provider down")
            return
            yield

        with patch("app.services.conversation.streaming.iter_ai_stream", fake_iter_ai_stream):
            events = list(
                stream_response_generator(
                    session_id=uuid4(),
                    stream_in=StreamInputs(
                        system_prompt="prompt",
                        effective_user_input="hola",
                        forced_text=None,
                    ),
                    context_messages=[],
                    ctx=_make_ctx(trainee_msg_id=uuid4(), previous_severity=2.8),
                )
            )

        self.assertEqual(len(events), 1)
        payload = _error_payload(events[0])
        self.assertIs(payload["discarded"], False)
        self.assertIn("Recarga la conversacion", payload["error"])
        mock_finalize.assert_not_called()

    @patch("app.services.conversation.streaming.finalize_and_evaluate_stream")
    @patch("app.services.conversation.streaming.commit_stream_message", return_value=False)
    @patch("app.services.conversation.core.SessionRepository")
    @patch("app.services.conversation.core.ConversationRepository")
    @patch("app.services.conversation.streaming.SessionLocal")
    def test_stream_response_generator_emits_error_when_commit_fails(
        self,
        mock_session_local,
        mock_conv_repo,
        mock_session_repo,
        _mock_commit,
        mock_finalize,
    ):
        gen_db = MagicMock()
        mock_session_local.return_value = gen_db
        session_row = SimpleNamespace(current_severity=3.4)
        mock_session_repo.get_by_id.return_value = session_row
        session_id = uuid4()
        trainee_msg_id = uuid4()

        events = list(
            stream_response_generator(
                session_id=session_id,
                stream_in=StreamInputs(
                    system_prompt=None,
                    effective_user_input="hola",
                    forced_text="respuesta corta",
                ),
                context_messages=[],
                ctx=_make_ctx(trainee_msg_id=trainee_msg_id, previous_severity=2.8),
            )
        )

        payload = _error_payload(events[-1])
        self.assertIs(payload["discarded"], True)
        self.assertIn("se descarto", payload["error"])
        mock_finalize.assert_not_called()
        mock_conv_repo.delete_by_id.assert_called_once_with(gen_db, session_id, trainee_msg_id)
        self.assertEqual(session_row.current_severity, 2.8)
