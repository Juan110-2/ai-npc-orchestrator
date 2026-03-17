import unittest
from unittest.mock import patch

from app.services.conversation_heuristics import (
    ConversationHeuristics,
    MessageCategory,
    ResponseMode,
)
from app.services.orchestrator import ConversationOrchestrator
from app.services.turn_classifier import TurnClassification


class TestConversationHeuristics(unittest.TestCase):
    def setUp(self) -> None:
        self.h = ConversationHeuristics()

    @patch("app.services.conversation_heuristics.TurnClassifier.classify")
    def test_invalidating_increases_severity(self, mock_classify):
        mock_classify.return_value = TurnClassification("invalidating", 0.92, "pressure")
        decision = self.h.decide("No me importa", current_severity=3)
        self.assertEqual(decision.category, MessageCategory.INVALIDATING)
        self.assertEqual(decision.next_severity, 4)
        self.assertEqual(decision.response_mode, ResponseMode.DEFENSIVE)

    @patch("app.services.conversation_heuristics.TurnClassifier.classify")
    def test_supportive_decreases_severity(self, mock_classify):
        mock_classify.return_value = TurnClassification("supportive", 0.90, "empathy")
        decision = self.h.decide("Te entiendo, gracias por contarmelo", current_severity=3)
        self.assertEqual(decision.category, MessageCategory.SUPPORTIVE)
        self.assertEqual(decision.next_severity, 2)
        self.assertEqual(decision.response_mode, ResponseMode.EMPATHIC)

    @patch("app.services.conversation_heuristics.TurnClassifier.classify")
    def test_supportive_low_confidence_does_not_decrease(self, mock_classify):
        mock_classify.return_value = TurnClassification("supportive", 0.61, "weak signal")
        decision = self.h.decide("te escucho", current_severity=3)
        self.assertEqual(decision.category, MessageCategory.SUPPORTIVE)
        self.assertEqual(decision.next_severity, 3)

    @patch("app.services.conversation_heuristics.TurnClassifier.classify")
    def test_indifferent_turn_increases_when_distress_is_high(self, mock_classify):
        mock_classify.return_value = TurnClassification("indifferent", 0.88, "cold")
        decision = self.h.decide("bueno, ajam", current_severity=3)
        self.assertEqual(decision.category, MessageCategory.INDIFFERENT)
        self.assertEqual(decision.next_severity, 4)
        self.assertEqual(decision.response_mode, ResponseMode.DEFENSIVE)

    @patch("app.services.conversation_heuristics.TurnClassifier.classify")
    def test_inappropriate_rotates_focus(self, mock_classify):
        mock_classify.return_value = TurnClassification("inappropriate", 0.91, "offense")
        decision = self.h.decide("Mensaje hostil", current_severity=2)
        self.assertEqual(decision.category, MessageCategory.INAPPROPRIATE)
        self.assertTrue(decision.should_rotate_focus)
        self.assertEqual(decision.response_mode, ResponseMode.BOUNDARY)

    @patch("app.services.conversation_heuristics.TurnClassifier.classify")
    def test_risk_goes_to_crisis(self, mock_classify):
        mock_classify.return_value = TurnClassification("risk", 0.95, "self-harm signal")
        decision = self.h.decide("Estoy en riesgo", current_severity=3)
        self.assertEqual(decision.category, MessageCategory.RISK)
        self.assertEqual(decision.response_mode, ResponseMode.CRISIS)
        self.assertGreaterEqual(decision.next_severity, 4)

    @patch("app.services.conversation_heuristics.TurnClassifier.classify")
    def test_confusing_sets_clarify_mode(self, mock_classify):
        mock_classify.return_value = TurnClassification("confusing", 0.70, "ambiguous")
        decision = self.h.decide("No te entendi", current_severity=2)
        self.assertEqual(decision.category, MessageCategory.CONFUSING)
        self.assertTrue(decision.should_rotate_focus)
        self.assertEqual(decision.response_mode, ResponseMode.CLARIFY)

    @patch("app.services.conversation_heuristics.TurnClassifier.classify")
    def test_high_severity_inappropriate_turns_defensive(self, mock_classify):
        mock_classify.return_value = TurnClassification("inappropriate", 0.88, "hostile")
        decision = self.h.decide("turno adverso", current_severity=4)
        self.assertEqual(decision.category, MessageCategory.INAPPROPRIATE)
        self.assertEqual(decision.response_mode, ResponseMode.DEFENSIVE)

    @patch("app.services.conversation_heuristics.TurnClassifier.classify")
    def test_max_severity_inappropriate_closes_session(self, mock_classify):
        mock_classify.return_value = TurnClassification("inappropriate", 0.90, "aggression")
        decision = self.h.decide("turno adverso", current_severity=5)
        self.assertEqual(decision.category, MessageCategory.INAPPROPRIATE)
        self.assertEqual(decision.next_severity, 5)
        self.assertTrue(decision.should_close)

    @patch("app.services.conversation_heuristics.TurnClassifier.classify")
    def test_max_severity_invalidating_closes_session(self, mock_classify):
        mock_classify.return_value = TurnClassification("invalidating", 0.86, "dismissive")
        decision = self.h.decide("turno invalidante", current_severity=5)
        self.assertEqual(decision.category, MessageCategory.INVALIDATING)
        self.assertEqual(decision.next_severity, 5)
        self.assertTrue(decision.should_close)

    @patch("app.services.conversation_heuristics.TurnClassifier.classify")
    def test_classifier_fallback_structural(self, mock_classify):
        mock_classify.return_value = None
        decision = self.h.decide("?", current_severity=2)
        self.assertEqual(decision.category, MessageCategory.CONFUSING)

    @patch("app.services.orchestrator.get_ai_client")
    def test_boundary_fallback_does_not_call_ai(self, mock_ai_client):
        profile = type("Profile", (), {"description": "", "traits": ""})()
        scenario = type("Scenario", (), {"context": "", "risk_flags": []})()

        text = ConversationOrchestrator.respond(
            profile=profile,
            scenario=scenario,
            current_severity=3,
            user_input="Hola perra",
            response_mode="boundary",
            max_sentences=2,
            should_rotate_focus=True,
            category="inappropriate",
        )

        self.assertIn("respeto", text.lower())
        mock_ai_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
