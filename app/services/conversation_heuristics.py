from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
import unicodedata
from typing import Tuple

from app.services.turn_classifier import TurnClassifier


class MessageCategory(str, Enum):
    SUPPORTIVE = "supportive"
    INDIFFERENT = "indifferent"
    NEUTRAL = "neutral"
    CONFUSING = "confusing"
    INVALIDATING = "invalidating"
    INAPPROPRIATE = "inappropriate"
    RISK = "risk"


class ResponseMode(str, Enum):
    EMPATHIC = "empathic"
    NEUTRAL = "neutral"
    CLARIFY = "clarify"
    DEFENSIVE = "defensive"
    BOUNDARY = "boundary"
    CRISIS = "crisis"


@dataclass(frozen=True)
class HeuristicDecision:
    category: MessageCategory
    next_severity: int
    should_close: bool
    should_rotate_focus: bool
    response_mode: ResponseMode
    max_sentences: int
    matched_rules: Tuple[str, ...] = field(default_factory=tuple)


class ConversationHeuristics:
    """Reglas rápidas y determinísticas para clasificar un turno y ajustar estado."""

    MIN_SEVERITY = 0   # 0 = paciente calmado, sesión puede cerrar
    MAX_SEVERITY = 5   # 5 = crisis, sesión cierra automáticamente

    CATEGORY_PRIORITY = (
        MessageCategory.RISK,
        MessageCategory.INAPPROPRIATE,
        MessageCategory.INVALIDATING,
        MessageCategory.INDIFFERENT,
        MessageCategory.SUPPORTIVE,
        MessageCategory.CONFUSING,
        MessageCategory.NEUTRAL,
    )

    def __init__(self) -> None:
        self.turn_classifier = TurnClassifier()

    def decide(self, user_text: str, current_severity: int) -> HeuristicDecision:
        normalized = self._normalize(user_text)
        category, matched_rules, confidence = self._classify(normalized)
        return self._apply_rules(
            category,
            current_severity,
            normalized,
            matched_rules,
            confidence,
        )

    def _classify(self, normalized_text: str) -> Tuple[MessageCategory, Tuple[str, ...], float]:
        if not normalized_text:
            return MessageCategory.CONFUSING, ("empty_message",), 0.0

        semantic = self.turn_classifier.classify(normalized_text)
        if semantic:
            try:
                category = MessageCategory(semantic.category)
                return (
                    category,
                    (
                        f"semantic:{semantic.source}:{semantic.category}:{semantic.confidence:.2f}",
                        f"rationale:{semantic.rationale}",
                    ),
                    float(semantic.confidence),
                )
            except ValueError:
                pass

        # Structural fallback without lexical word lists.
        if len(normalized_text) <= 2:
            return MessageCategory.CONFUSING, ("fallback:too_short",), 0.4
        if not any(char.isalpha() for char in normalized_text):
            return MessageCategory.CONFUSING, ("fallback:no_alpha",), 0.4

        return MessageCategory.NEUTRAL, ("fallback:neutral",), 0.5

    def _apply_rules(
        self,
        category: MessageCategory,
        current_severity: int,
        normalized_text: str,
        matched_rules: Tuple[str, ...],
        confidence: float,
    ) -> HeuristicDecision:
        severity = self._clamp(current_severity)
        confidence = max(0.0, min(1.0, float(confidence)))

        next_severity = severity
        should_close = False
        should_rotate_focus = False
        response_mode = ResponseMode.NEUTRAL
        max_sentences = 3

        if category == MessageCategory.SUPPORTIVE:
            # No bajar severidad de forma automatica por un solo turno de apoyo.
            # Exigimos una senal semantica relativamente fuerte.
            if confidence >= 0.82 and len(normalized_text) >= 10 and severity >= 2:
                next_severity = self._clamp(severity - 1)
            else:
                next_severity = severity
            response_mode = ResponseMode.EMPATHIC
            if next_severity <= 1 and confidence >= 0.9:
                should_close = True

        elif category == MessageCategory.INDIFFERENT:
            # La indiferencia no contiene: con malestar medio-alto tiende a empeorar.
            next_severity = self._clamp(severity + 1 if severity >= 3 else severity)
            response_mode = ResponseMode.DEFENSIVE if severity >= 3 else ResponseMode.CLARIFY
            max_sentences = 2

        elif category == MessageCategory.NEUTRAL:
            next_severity = severity
            response_mode = ResponseMode.NEUTRAL

        elif category == MessageCategory.CONFUSING:
            next_severity = severity
            should_rotate_focus = True
            response_mode = ResponseMode.CLARIFY
            max_sentences = 2

        elif category == MessageCategory.INVALIDATING:
            next_severity = self._clamp(severity + 1)
            response_mode = ResponseMode.DEFENSIVE
            max_sentences = 2

        elif category == MessageCategory.INAPPROPRIATE:
            next_severity = self._clamp(severity + 1)
            should_rotate_focus = True
            # Si ya hay malestar alto, responde con más carga emocional.
            response_mode = ResponseMode.DEFENSIVE if severity >= 4 else ResponseMode.BOUNDARY
            max_sentences = 2

        elif category == MessageCategory.RISK:
            next_severity = self._clamp(max(severity + 1, 4))
            response_mode = ResponseMode.CRISIS
            max_sentences = 2
            if severity >= 4:
                should_close = True

        # Cierre por deterioro maximo: al llegar al pico de severidad con un turno adverso,
        # se termina la sesion para representar "peor escenario" de forma controlada.
        if next_severity >= self.MAX_SEVERITY and category in (
            MessageCategory.RISK,
            MessageCategory.INDIFFERENT,
            MessageCategory.INVALIDATING,
            MessageCategory.INAPPROPRIATE,
        ):
            should_close = True
            if category == MessageCategory.RISK:
                response_mode = ResponseMode.CRISIS
            elif response_mode == ResponseMode.NEUTRAL:
                response_mode = ResponseMode.DEFENSIVE
            max_sentences = min(max_sentences, 2)

        return HeuristicDecision(
            category=category,
            next_severity=next_severity,
            should_close=should_close,
            should_rotate_focus=should_rotate_focus,
            response_mode=response_mode,
            max_sentences=max_sentences,
            matched_rules=tuple(matched_rules),
        )

    @staticmethod
    def _normalize(text: str) -> str:
        normalized = (text or "").strip().lower()
        normalized = unicodedata.normalize("NFKD", normalized)
        normalized = "".join(c for c in normalized if not unicodedata.combining(c))
        # Captura variantes como "perrrra" sin usar fuzzy matching costoso.
        normalized = re.sub(r"([a-z])\1{2,}", r"\1\1", normalized)
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized

    def _clamp(self, v