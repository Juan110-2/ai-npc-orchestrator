import unittest
from types import SimpleNamespace

from app.services.conversation.core import apply_closed_session_state, compute_closing_state
from app.services.conversation.heuristics import MessageCategory


def _patient_message(severity: float) -> SimpleNamespace:
    return SimpleNamespace(role="patient", severity=severity)


def _decision(category: MessageCategory) -> SimpleNamespace:
    return SimpleNamespace(category=category)


class TestComputeClosingStateCrisisKind(unittest.TestCase):
    """
    compute_closing_state decide closing_kind="crisis_riesgo" (revelacion real de
    riesgo) vs "crisis" (deterioro emocional generico) segun la categoria del
    turno que cierra. Antes de este arreglo solo revisaba MessageCategory.RISK,
    asi que una revelacion real surgida de una pregunta de cuidado (clasificada
    correctamente como RISK_CHECK) caia en el "crisis" generico -- perdiendo la
    senal de que hubo contenido de riesgo real, justo el caso de Maria en la
    ronda de pruebas con Gemini.
    """

    def test_crisis_riesgo_when_closing_turn_is_risk(self):
        history = [_patient_message(5.0), _patient_message(4.7)]
        result = compute_closing_state(
            current_severity=4.7,
            context_history=history,
            decision=_decision(MessageCategory.RISK),
            previous_severity=4.7,
            b_min=0.0,
            b_max=5.0,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["kind"], "crisis_riesgo")

    def test_crisis_riesgo_when_closing_turn_is_risk_check(self):
        history = [_patient_message(5.0), _patient_message(4.7)]
        result = compute_closing_state(
            current_severity=4.7,
            context_history=history,
            decision=_decision(MessageCategory.RISK_CHECK),
            previous_severity=4.7,
            b_min=0.0,
            b_max=5.0,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["kind"], "crisis_riesgo")

    def test_crisis_generic_when_no_risk_category(self):
        history = [_patient_message(5.0), _patient_message(4.7)]
        result = compute_closing_state(
            current_severity=4.7,
            context_history=history,
            decision=_decision(MessageCategory.SUPPORTIVE),
            previous_severity=4.7,
            b_min=0.0,
            b_max=5.0,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["kind"], "crisis")


class TestApplyClosedSessionStateStatus(unittest.TestCase):
    def _status_after_closing(self, closing_kind: str) -> str:
        session = SimpleNamespace(current_severity=4.5, status="active", ended_at=None)
        ctx = SimpleNamespace(closing_kind=closing_kind, b_min=0.0, b_max=5.0)
        apply_closed_session_state(session, ctx)
        return session.status

    def test_cierres_adversos_quedan_terminated(self):
        for closing_kind in ("crisis", "crisis_riesgo", "inappropriate"):
            self.assertEqual(self._status_after_closing(closing_kind), "terminated")

    def test_cierre_por_exito_queda_completed(self):
        self.assertEqual(self._status_after_closing("success"), "completed")


if __name__ == "__main__":
    unittest.main()
