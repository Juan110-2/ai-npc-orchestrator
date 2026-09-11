import unittest
from unittest.mock import MagicMock, patch

from app.services.conversation.classifier import (
    detect_npc_farewell,
    has_farewell_candidate_words,
)
from app.services.conversation.core import maybe_close_on_npc_farewell
from app.services.conversation.heuristics import MessageCategory, ResponseMode
from app.services.conversation.models import TurnContext


def _make_ctx(should_close: bool, closing_kind: str | None = None) -> TurnContext:
    decision = MagicMock()
    decision.category = MessageCategory.NEUTRAL
    decision.response_mode = ResponseMode.NEUTRAL
    return TurnContext(
        decision=decision,
        forced_close=False,
        closing=None,
        should_close=should_close,
        closing_kind=closing_kind,
        context_history=[],
        final_severity=2.0,
        b_min=0.0,
        b_max=5.0,
        behavioral_flags=(),
    )


class TestFarewellCandidateFilter(unittest.TestCase):
    """El filtro barato (sin IA) que decide si vale la pena llamar a la IA."""

    def test_detects_common_farewell_phrasings(self):
        cases = [
            "Necesito irme un rato a ordenarme la cabeza.",
            "Prefiero cortar acá por hoy.",
            "No puedo seguir hablando de esto ahora mismo.",
            "Mejor lo dejamos aquí por hoy.",
            "Necesito estar solo un rato.",
            "Ahora mismo necesito alejarme de esta conversación.",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertTrue(has_farewell_candidate_words(text))

    def test_ignores_unrelated_sad_text(self):
        cases = [
            "Hoy me siento cansada de todo, pero gracias por escuchar.",
            "Me duele mucho lo que pasó con mi papá.",
            "Gracias por preguntarme, de verdad lo aprecio.",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertFalse(has_farewell_candidate_words(text))


class TestDetectNpcFarewell(unittest.TestCase):
    """detect_npc_farewell: el filtro debe evitar la llamada a la IA cuando
    no hay ningun candidato en el texto."""

    @patch("app.services.conversation.classifier.get_ai_client")
    def test_skips_ai_call_when_no_candidate_words(self, mock_get_client):
        result = detect_npc_farewell("Gracias por escucharme, me ayuda mucho hablar de esto.")
        self.assertFalse(result)
        mock_get_client.assert_not_called()

    @patch("app.services.conversation.classifier.get_ai_client")
    def test_calls_ai_and_confirms_when_candidate_present(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.generate_response.return_value = MagicMock(content="si")
        mock_get_client.return_value = mock_client

        result = detect_npc_farewell("Necesito irme un rato, no puedo seguir con esto.")
        self.assertTrue(result)
        mock_client.generate_response.assert_called_once()

    @patch("app.services.conversation.classifier.get_ai_client")
    def test_calls_ai_but_can_reject_ambiguous_distress(self, mock_get_client):
        # "no puedo mas" es candidato lexico, pero la IA puede decidir que no
        # es una despedida real (solo angustia) -- el filtro no decide solo.
        mock_client = MagicMock()
        mock_client.generate_response.return_value = MagicMock(content="no")
        mock_get_client.return_value = mock_client

        result = detect_npc_farewell("No puedo más con todo esto, es muy difícil.")
        self.assertFalse(result)
        mock_client.generate_response.assert_called_once()


class TestMaybeCloseOnNpcFarewell(unittest.TestCase):
    def test_short_circuits_when_already_closing(self):
        ctx = _make_ctx(should_close=True, closing_kind="crisis")
        with patch("app.services.conversation.core.detect_npc_farewell") as mock_detect:
            result = maybe_close_on_npc_farewell(
                ctx=ctx, npc_text="cualquier cosa", db=MagicMock(), session_id="s1"
            )
        mock_detect.assert_not_called()
        self.assertIs(result, ctx)

    @patch("app.services.conversation.core.detect_npc_farewell", return_value=False)
    def test_keeps_ctx_when_no_farewell_detected(self, _mock_detect):
        ctx = _make_ctx(should_close=False)
        result = maybe_close_on_npc_farewell(
            ctx=ctx, npc_text="Gracias por escuchar.", db=MagicMock(), session_id="s1"
        )
        self.assertFalse(result.should_close)
        self.assertIsNone(result.closing_kind)

    @patch("app.services.conversation.core.detect_npc_farewell", return_value=True)
    def test_closes_session_as_self_paced_when_farewell_detected(self, _mock_detect):
        ctx = _make_ctx(should_close=False)
        result = maybe_close_on_npc_farewell(
            ctx=ctx, npc_text="Necesito irme un rato.", db=MagicMock(), session_id="s1"
        )
        self.assertTrue(result.should_close)
        self.assertEqual(result.closing_kind, "self_paced")


if __name__ == "__main__":
    unittest.main()
