import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.conversation_message import ConversationMessage
from app.models.sessions import Session as _SessionModel  # noqa: F401  (resuelve la FK a sessions)
from app.services.conversation.core import rollback_turn


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


class TestRollbackBorraRespuestaHuerfana(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine, tables=[ConversationMessage.__table__])
        self.db = sessionmaker(bind=engine)()
        self.session_id = uuid4()
        self.t0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.db.close()

    def _add(self, role, minutes, content=None):
        msg = ConversationMessage(
            session_id=self.session_id,
            role=role,
            content=content or f"{role}-{minutes}",
            severity=2.5,
            risk_flags=[],
            created_at=self.t0 + timedelta(minutes=minutes),
        )
        self.db.add(msg)
        self.db.commit()
        return msg.id

    def _contents(self):
        rows = self.db.query(ConversationMessage).order_by(ConversationMessage.created_at).all()
        return [r.content for r in rows]

    def test_borra_trainee_y_respuesta_del_turno_sin_tocar_turnos_previos(self):
        self._add("trainee", 0, "turno1-trainee")
        self._add("patient", 1, "turno1-patient")
        trainee_id = self._add("trainee", 2, "turno2-trainee")
        self._add("patient", 3, "turno2-patient-huerfano")

        ok = rollback_turn(
            self.db, self.session_id, trainee_msg_id=trainee_id, previous_severity=None
        )

        self.assertTrue(ok)
        self.assertEqual(self._contents(), ["turno1-trainee", "turno1-patient"])

    def test_sin_respuesta_guardada_solo_borra_el_trainee(self):
        self._add("trainee", 0, "turno1-trainee")
        self._add("patient", 1, "turno1-patient")
        trainee_id = self._add("trainee", 2, "turno2-trainee")

        ok = rollback_turn(
            self.db, self.session_id, trainee_msg_id=trainee_id, previous_severity=None
        )

        self.assertTrue(ok)
        self.assertEqual(self._contents(), ["turno1-trainee", "turno1-patient"])

    def test_no_toca_mensajes_de_otra_sesion(self):
        otro = ConversationMessage(
            session_id=uuid4(),
            role="patient",
            content="otra-sesion",
            severity=1.0,
            risk_flags=[],
            created_at=self.t0 + timedelta(minutes=10),
        )
        self.db.add(otro)
        self.db.commit()
        trainee_id = self._add("trainee", 2)
        self._add("patient", 3)

        rollback_turn(self.db, self.session_id, trainee_msg_id=trainee_id, previous_severity=None)

        self.assertEqual(self._contents(), ["otra-sesion"])


if __name__ == "__main__":
    unittest.main()
