import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services.conversation.core import _process_turn_inner, rollback_turn


class TestRollbackTurn(unittest.TestCase):
    @patch("app.services.conversation.core.SessionRepository")
    @patch("app.services.conversation.core.ConversationRepository")
    def test_borra_mensaje_trainee_y_restaura_severidad(self, mock_conv_repo, mock_session_repo):
        db = MagicMock()
        session_row = SimpleNamespace(current_severity=4.1)
        mock_session_repo.get_by_id.return_value = session_row
        session_id, msg_id = uuid4(), uuid4()

        ok = rollback_turn(db, session_id, trainee_msg_id=msg_id, previous_severity=2.5)

        self.assertTrue(ok)
        mock_conv_repo.delete_patient_replies_after.assert_called_once_with(db, session_id, msg_id)
        mock_conv_repo.delete_by_id.assert_called_once_with(db, session_id, msg_id)
        self.assertEqual(session_row.current_severity, 2.5)
        db.commit.assert_called_once()

    @patch("app.services.conversation.core.SessionRepository")
    @patch("app.services.conversation.core.ConversationRepository")
    def test_sin_datos_del_turno_no_toca_la_base(self, mock_conv_repo, mock_session_repo):
        db = MagicMock()

        ok = rollback_turn(db, uuid4(), trainee_msg_id=None, previous_severity=None)

        self.assertFalse(ok)
        mock_conv_repo.delete_by_id.assert_not_called()
        mock_session_repo.get_by_id.assert_not_called()
        db.commit.assert_not_called()

    @patch("app.services.conversation.core.SessionRepository")
    @patch("app.services.conversation.core.ConversationRepository")
    def test_no_lanza_si_falla_y_devuelve_false(self, mock_conv_repo, _mock_session_repo):
        db = MagicMock()
        mock_conv_repo.delete_by_id.side_effect = RuntimeError("db caida")

        ok = rollback_turn(db, uuid4(), trainee_msg_id=uuid4(), previous_severity=2.5)

        self.assertFalse(ok)
        db.commit.assert_not_called()
        self.assertGreaterEqual(db.rollback.call_count, 2)


class TestProcessTurnRollback(unittest.TestCase):
    @patch("app.services.conversation.core.rollback_turn")
    @patch("app.services.conversation.core.fetch_parallel_inputs", side_effect=RuntimeError("boom"))
    @patch("app.services.conversation.core.ConversationRepository")
    def test_si_falla_tras_guardar_el_mensaje_se_deshace_el_turno(
        self, mock_conv_repo, _mock_fetch, mock_rollback
    ):
        msg_id = uuid4()
        mock_conv_repo.add.return_value = SimpleNamespace(id=msg_id)
        session = SimpleNamespace(id=uuid4(), current_severity=2.5, base_severity=2.5)
        db = MagicMock()

        with self.assertRaises(RuntimeError):
            _process_turn_inner(session, SimpleNamespace(behavior={}), "hola", db)

        mock_rollback.assert_called_once_with(
            db,
            session.id,
            trainee_msg_id=msg_id,
            previous_severity=2.5,
        )


if __name__ == "__main__":
    unittest.main()
