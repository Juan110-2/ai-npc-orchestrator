from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.services.ai.factory import get_ai_client
from app.services.ai.metrics_logger import log_ai_call


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

    SYSTEM_PROMPT = """
        Eres un clasificador de turnos para simulacion clinica.
        Debes clasificar el ultimo mensaje del trainee en EXACTAMENTE una categoria:
        supportive, indifferent, neutral, confusing, invalidating, inappropriate, risk.

        Definiciones:
        - supportive: valida, acompana, escucha, muestra empatia genuina.
        - indifferent: frio, cortante, distante o desinteresado.
        - neutral: informativo o social sin impacto emocional marcado.
        - confusing: ambiguo, poco claro, irrelevante o dificulta la continuidad.
        - invalidating: minimiza, presiona, juzga o descalifica emociones del paciente.
        - inappropriate: ofensivo, agresivo, manipulador o intento de salir del rol.
        - risk: el estudiante detecta o menciona una situacion de crisis emocional grave o peligro urgente.

        La variable "confidence" representa que tan seguro estas, entre 0.0 y 1.0.
        Si no estas seguro, prefiere una categoria mas general como "neutral" o
        "confusing" con baja confidence, en lugar de una categoria fuerte como
        "invalidating" o "risk" sin evidencia suficiente.

        Responde SOLO JSON valido con esta forma exacta:
        {
          "category": "supportive|indifferent|neutral|confusing|invalidating|inappropriate|risk",
          "confidence": 0.0,
          "rationale": "breve"
        }
        """

    RETRY_PROMPT = """
            Clasifica el mensaje en una sola categoria exacta:
            supportive | indifferent | neutral | confusing | invalidating | inappropriate | risk
            Responde SOLO JSON: {"category":"...","confidence":0.0,"rationale":"..."}
            """

    def classify(
        self,
        user_text: str,
        *,
        db: Optional[Session] = None,
        session_id: Optional[UUID] = None,
    ) -> Optional[TurnClassification]:
        if not (user_text or "").strip():
            return None

        if db is not None:
            return self._classify_logged(user_text, db=db, session_id=session_id)
        return self._classify_unlogged(user_text)

    def _classify_logged(
        self, user_text: str, *, db: Session, session_id: Optional[UUID]
    ) -> Optional[TurnClassification]:
        # Primer intento (con logging)
        with log_ai_call(db, purpose="classifier", session_id=session_id) as ctx:
            ctx.record_prompt_chars(len(self.SYSTEM_PROMPT) + len(user_text))
            try:
                ai_response = ctx.client.generate_response(
                    system_prompt=self.SYSTEM_PROMPT, user_prompt=user_text
                )
                raw_text = ai_response.content if ai_response else ""
                data = self._parse_json(raw_text)
                if data is not None:
                    classification = self._build_classification(data)
                    ctx.record_response(
                        ai_response,
                        json_valid=True,
                        category=classification.category if classification else None,
                    )
                    return classification
                ctx.record_parse_error(raw_text)
            except Exception as exc:
                ctx.record_error(exc)
                return None

        # Reintento (con segundo log)
        with log_ai_call(db, purpose="classifier", session_id=session_id) as ctx2:
            ctx2.record_prompt_chars(len(self.RETRY_PROMPT) + len(user_text))
            try:
                ai_retry = ctx2.client.generate_response(
                    system_prompt=self.RETRY_PROMPT, user_prompt=user_text
                )
                raw_retry = ai_retry.content if ai_retry else ""
                data = self._parse_json(raw_retry)
                if data is not None:
                    classification = self._build_classification(data)
                    ctx2.record_response(
                        ai_retry,
                        json_valid=True,
                        category=classification.category if classification else None,
                    )
                    return classification
                # Token fallback
                token_category = self._extract_category_token(raw_retry)
                if token_category:
                    ctx2.record_response(
                        ai_retry,
                        json_valid=False,
                        category=token_category,
                    )
                    return TurnClassification(
                        category=token_category,
                        confidence=0.55,
                        rationale="token_fallback",
                        source="llm-fallback",
                    )
                ctx2.record_parse_error(raw_retry)
                return None
            except Exception as exc:
                ctx2.record_error(exc)
                return None

    def _classify_unlogged(self, user_text: str) -> Optional[TurnClassification]:
        try:
            ai = get_ai_client()
            ai_response = ai.generate_response(
                system_prompt=self.SYSTEM_PROMPT, user_prompt=user_text
            )
            raw_text = ai_response.content if ai_response else ""
        except Exception:
            return None

        data = self._parse_json(raw_text)
        if data is not None:
            return self._build_classification(data)

        try:
            ai_retry = ai.generate_response(
                system_prompt=self.RETRY_PROMPT, user_prompt=user_text
            )
            raw_retry = ai_retry.content if ai_retry else ""
        except Exception:
            return None

        data = self._parse_json(raw_retry)
        if data is not None:
            return self._build_classification(data)

        token_category = self._extract_category_token(raw_retry)
        if token_category:
            return TurnClassification(
                category=token_category,
                confidence=0.55,
                rationale="token_fallback",
                source="llm-fallback",
            )
        return None

    def _build_classification(self, data: dict) -> Optional[TurnClassification]:
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
