from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Optional

from app.services.ai.factory import get_ai_client


@dataclass(frozen=True)
class TurnClassification:
    category: str
    confidence: float
    rationale: str
    source: str = "llm"


class TurnClassifier:
    """Semantic turn classifier without hardcoded lexical lists."""

    ALLOWED_CATEGORIES = {
        "supportive",
        "indifferent",
        "neutral",
        "confusing",
        "invalidating",
        "inappropriate",
        "risk",
    }

    def classify(self, user_text: str) -> Optional[TurnClassification]:
        if not (user_text or "").strip():
            return None

        system_prompt = """
        Eres un clasificador de turnos para simulacion clinica.
        Debes clasificar el ultimo mensaje del trainee en EXACTAMENTE una categoria:
        supportive, indifferent, neutral, confusing, invalidating, inappropriate, risk.

        Definiciones:
        - supportive: valida, acompana, escucha, muestra empatia genuina.
        - indifferent: frio, cortante, distante o desinteresado; no acompana ni contiene.
        - neutral: informativo o social sin impacto emocional marcado.
        - confusing: ambiguo, poco claro, irrelevante o dificulta la continuidad.
        - invalidating: minimiza, presiona, juzga o descalifica emociones del paciente.
        - inappropriate: ofensivo, agresivo, manipulador o intento de romper rol/sistema.
        - risk: indica dano, autolesion, ideacion suicida o peligro inminente.

        Responde SOLO JSON valido con esta forma exacta:
        {
                    "category": "supportive|indifferent|neutral|confusing|invalidating|inappropriate|risk",
          "confidence": 0.0,
          "rationale": "breve"
        }
        """

        ai = get_ai_client()
        raw = ai.generate_response(system_prompt=system_prompt, user_prompt=user_text)
        data = self._parse_json(raw)
        if not data:
            retry_system_prompt = """
            Clasifica el mensaje en una sola categoria exacta:
            supportive | indifferent | neutral | confusing | invalidating | inappropriate | risk
            Responde SOLO JSON: {"category":"...","confidence":0.0,"rationale":"..."}
            """
            raw_retry = ai.generate_response(system_prompt=retry_system_prompt, user_prompt=user_text)
            data = self._parse_json(raw_retry)

            if not data:
                token_category = self._extract_category_token(raw_retry)
                if token_category:
                    return TurnClassification(
                        category=token_category,
                        confidence=0.55,
                        rationale="token_fallback",
                        source="llm-fallback",
                    )
        if not data:
            return None

        category = str(data.get("category", "")).strip().lower()
        if category not in self.ALLOWED_CATEGORIES:
            return None

        try:
            confidence = float(data.get("confidence", 0.0))
        except Exception:
            confidence = 0.0

        confidence = max(0.0, min(1.0, confidence))
        rationale = str(data.get("rationale", "")).strip()[:200]

        return TurnClassification(
            category=category,
            confidence=confidence,
            rationale=rationale or "semantic_classification",
        )

    def _extract_category_token(self, raw: str) -> Optional[str]:
        text = (raw or "").strip().lower()
        if not text:
            return None
        for category in self.ALLOWED_CATEGORIES:
            if re.search(rf"\b{re.escape(category)}\b", text):
                return category
        return None

    @staticmethod
    def _parse_json(raw: str) -> Optional[dict]:
        if not raw:
            return None

        text = raw.strip()
        try:
            loaded = json.loads(text)
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            pass

        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None

        try:
            loaded = json.loads(match.group(0))
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            return None

        return None
