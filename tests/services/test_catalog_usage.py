"""
Borrado seguro y uso de perfiles/escenarios (`app/repositories/catalog_usage.py`).

Sin base de datos: `db` es un mock que registra el SQL (dialecto PostgreSQL) de cada
sentencia, para comprobar el orden de bloqueos y que el borrado de sesiones sea a nivel SQL.
"""
import unittest
from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.models.profile import Profile
from app.models.scenario import Scenario
from app.models.sessions import Session as SessionModel
from app.repositories.catalog_usage import (
    BLOCKED,
    DELETED,
    NOT_FOUND,
    delete_case_if_unused,
    get_case_usage,
)


def _result(first=None, scalars=None, scalar=None):
    res = MagicMock()
    res.first.return_value = first
    res.scalars.return_value.all.return_value = scalars or []
    res.scalar_one.return_value = scalar
    return res


def _fake_db(results):
    """Mock de `db` cuyo `execute` devuelve `results` en orden y guarda el SQL ejecutado."""
    db = MagicMock()
    db.sql = []
    pending = list(results)

    def execute(stmt, *args, **kwargs):
        db.sql.append(str(stmt.compile(dialect=postgresql.dialect())))
        return pending.pop(0)

    db.execute.side_effect = execute
    return db


class TestDeleteCaseIfUnused(unittest.TestCase):
    def test_orden_de_bloqueos_y_borrado_sin_actividad(self):
        s1, s2 = uuid4(), uuid4()
        db = _fake_db([
            _result(first=(1,)),              # 1. FOR UPDATE del escenario
            _result(scalars=[s1, s2]),        # 2. FOR UPDATE de sus sesiones
            _result(scalar=0),                # 3. conteo de actividad
            _result(),                        # 4a. DELETE sessions
            _result(),                        # 4b. DELETE scenarios
        ])

        result = delete_case_if_unused(db, Scenario, SessionModel.scenario_id, uuid4())

        self.assertEqual((result.status, result.deleted_sessions), (DELETED, 2))
        sql = db.sql
        self.assertEqual(len(sql), 5)
        self.assertIn("FROM scenarios", sql[0])
        self.assertTrue(sql[0].rstrip().endswith("FOR UPDATE"))
        self.assertIn("FROM sessions", sql[1])
        self.assertIn("sessions.scenario_id", sql[1])
        self.assertTrue(sql[1].rstrip().endswith("FOR UPDATE"))
        self.assertIn("count(*)", sql[2])
        for tabla in ("conversation_messages", "session_evaluations", "ai_call_logs"):
            self.assertIn(tabla, sql[2])
        self.assertTrue(sql[3].startswith("DELETE FROM sessions"))
        self.assertTrue(sql[4].startswith("DELETE FROM scenarios"))
        db.commit.assert_called_once()
        db.delete.assert_not_called()  # nada de db.delete(obj) del ORM

    def test_con_actividad_hace_rollback_y_no_borra(self):
        db = _fake_db([
            _result(first=(1,)),
            _result(scalars=[uuid4(), uuid4(), uuid4()]),
            _result(scalar=2),
        ])

        result = delete_case_if_unused(db, Profile, SessionModel.profile_id, uuid4())

        self.assertEqual((result.status, result.sessions_with_activity), (BLOCKED, 2))
        self.assertEqual(len(db.sql), 3)
        self.assertFalse(any(q.startswith("DELETE") for q in db.sql))
        db.rollback.assert_called()
        db.commit.assert_not_called()

    def test_sin_sesiones_solo_borra_el_caso(self):
        db = _fake_db([_result(first=(1,)), _result(scalars=[]), _result()])

        result = delete_case_if_unused(db, Profile, SessionModel.profile_id, uuid4())

        self.assertEqual((result.status, result.deleted_sessions), (DELETED, 0))
        self.assertEqual(len(db.sql), 3)  # sin conteo ni DELETE de sesiones
        self.assertTrue(db.sql[2].startswith("DELETE FROM profiles"))
        db.commit.assert_called_once()

    def test_caso_inexistente_devuelve_not_found(self):
        db = _fake_db([_result(first=None)])

        result = delete_case_if_unused(db, Scenario, SessionModel.scenario_id, uuid4())

        self.assertEqual(result.status, NOT_FOUND)
        self.assertEqual(len(db.sql), 1)
        db.rollback.assert_called()
        db.commit.assert_not_called()

    def test_integrity_error_hace_rollback_y_se_propaga(self):
        db = MagicMock()
        db.execute.side_effect = IntegrityError("DELETE", {}, Exception("fk"))

        with self.assertRaises(IntegrityError):
            delete_case_if_unused(db, Scenario, SessionModel.scenario_id, uuid4())

        db.rollback.assert_called()
        db.commit.assert_not_called()


class TestGetCaseUsage(unittest.TestCase):
    def test_conteos(self):
        db = _fake_db([_result(first=(1,)), _result(scalar=5), _result(scalar=2)])

        usage = get_case_usage(db, Scenario, SessionModel.scenario_id, uuid4())

        self.assertEqual((usage.total_sessions, usage.sessions_with_activity), (5, 2))
        self.assertEqual(usage.unused_sessions, 3)
        self.assertFalse(usage.can_delete)
        self.assertFalse(any("FOR UPDATE" in q for q in db.sql))  # consulta sin bloqueos

    def test_sin_actividad_se_puede_borrar(self):
        db = _fake_db([_result(first=(1,)), _result(scalar=2), _result(scalar=0)])

        usage = get_case_usage(db, Profile, SessionModel.profile_id, uuid4())

        self.assertTrue(usage.can_delete)
        self.assertEqual(usage.unused_sessions, 2)

    def test_inexistente_devuelve_none(self):
        db = _fake_db([_result(first=None)])

        self.assertIsNone(get_case_usage(db, Profile, SessionModel.profile_id, uuid4()))


if __name__ == "__main__":
    unittest.main()
