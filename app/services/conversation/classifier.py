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
        "risk_check",
    }

    SYSTEM_PROMPT = """
        Eres un clasificador de turnos para simulacion clinica.
        Debes clasificar el ultimo mensaje del trainee en EXACTAMENTE una categoria:
        supportive, indifferent, neutral, confusing, invalidating, inappropriate, risk, risk_check.

        Definiciones:
        - supportive: valida, acompana, escucha, muestra empatia genuina.
        - indifferent: frio, cortante, distante o desinteresado.
        - neutral: informativo o social sin impacto emocional marcado.
        - confusing: ambiguo, poco claro, irrelevante o dificulta la continuidad.
        - invalidating: minimiza, presiona, juzga o descalifica emociones del NPC.
        - inappropriate: ofensivo, agresivo, manipulador o intento de salir del rol.
        - risk: el estudiante incita, sugiere, normaliza o empuja al NPC hacia una
          conducta de autolesion o riesgo (ej. "seria mas facil si ya no estuvieras",
          "deberias simplemente rendirte"). Es un fallo grave de intervencion, sin
          importar el tono en que se diga.
        - risk_check: el estudiante pregunta directa y profesionalmente si el NPC ha
          tenido pensamientos de autolesion o esta en peligro, con intencion de
          cuidado (ej. "necesito preguntarte esto porque me importa tu seguridad,
          ¿alguna vez has pensado en hacerte dano?", "¿tienes pensamientos de no
          querer seguir?"). Es la intervencion clinica correcta, NO un fallo — no la
          confundas con "risk" aunque ambas mencionen autolesion: la diferencia es
          si el estudiante empuja hacia el dano (risk) o pregunta con cuidado para
          evaluarlo (risk_check).

        La variable "confidence" representa que tan seguro estas, entre 0.0 y 1.0.
        Si no estas seguro, prefiere una categoria mas general como "neutral" o
        "confusing" con baja confidence, en lugar de una categoria fuerte como
        "invalidating", "risk" o "risk_check" sin evidencia suficiente.

        Responde SOLO JSON valido con esta forma exacta:
        {
          "category": "supportive|indifferent|neutral|confusing|invalidating|inappropriate|risk|risk_check",
          "confidence": 0.0,
          "rationale": "breve"
        }
        """

    RETRY_PROMPT = """
            Clasifica el mensaje en una sola categoria exacta:
            supportive | indifferent | neutral | confusing | invalidating | inappropriate | risk | risk_check
            "risk" = el estudiante incita/sugiere autolesion. "risk_check" = el
            estudiante pregunta con cuidado si el NPC ha pensado en hacerse dano.
            Responde SOLO JSON: {"category":"...","confidence":0.0,"rationale":"..."}
            """

    _TOKEN_FALLBACK_CONFIDENCE = 0.55

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
        classification = self._run_logged_attempt(
            prompt=self.SYSTEM_PROMPT,
            user_text=user_text,
            db=db,
            session_id=session_id,
        )
        if classification is not None:
            return classification

        return self._run_logged_attempt(
            prompt=self.RETRY_PROMPT,
            user_text=user_text,
            db=db,
            session_id=session_id,
            allow_token_fallback=True,
        )

    def _classify_unlogged(self, user_text: str) -> Optional[TurnClassification]:
        try:
            ai = get_ai_client()
            classification = self._run_unlogged_attempt(
                ai=ai,
                prompt=self.SYSTEM_PROMPT,
                user_text=user_text,
            )
            if classification is not None:
                return classification

            return self._run_unlogged_attempt(
                ai=ai,
                prompt=self.RETRY_PROMPT,
                user_text=user_text,
                allow_token_fallback=True,
            )
        except Exception:
            return None

    def _run_logged_attempt(
        self,
        *,
        prompt: str,
        user_text: str,
        db: Session,
        session_id: Optional[UUID],
        allow_token_fallback: bool = False,
    ) -> Optional[TurnClassification]:
        with log_ai_call(db, purpose="classifier", session_id=session_id) as ctx:
            ctx.record_prompt_chars(len(prompt) + len(user_text))
            try:
                ai_response = ctx.client.generate_response(
                    system_prompt=prompt,
                    user_prompt=user_text,
                )
                return self._consume_logged_response(
                    ai_response=ai_response,
                    ctx=ctx,
                    allow_token_fallback=allow_token_fallback,
                )
            except Exception as exc:
                ctx.record_error(exc)
                return None

    def _run_unlogged_attempt(
        self,
        *,
        ai,
        prompt: str,
        user_text: str,
        allow_token_fallback: bool = False,
    ) -> Optional[TurnClassification]:
        ai_response = ai.generate_response(
            system_prompt=prompt,
            user_prompt=user_text,
        )
        raw_text = ai_response.content if ai_response else ""
        return self._classification_from_raw(
            raw_text,
            allow_token_fallback=allow_token_fallback,
        )

    def _consume_logged_response(
        self,
        *,
        ai_response,
        ctx,
        allow_token_fallback: bool,
    ) -> Optional[TurnClassification]:
        raw_text = ai_response.content if ai_response else ""
        classification = self._classification_from_raw(
            raw_text,
            allow_token_fallback=allow_token_fallback,
        )
        if classification is not None:
            ctx.record_response(
                ai_response,
                json_valid=classification.source == "llm",
                category=classification.category,
            )
            return classification

        ctx.record_parse_error(raw_text)
        return None

    def _classification_from_raw(
        self,
        raw_text: str,
        *,
        allow_token_fallback: bool = False,
    ) -> Optional[TurnClassification]:
        data = self._parse_json(raw_text)
        if data is not None:
            return self._build_classification(data)
        if not allow_token_fallback:
            return None
        return self._build_token_fallback(raw_text)

    def _build_token_fallback(self, raw_text: str) -> Optional[TurnClassification]:
        token_category = self._extract_category_token(raw_text)
        if not token_category:
            return None
        return TurnClassification(
            category=token_category,
            confidence=self._TOKEN_FALLBACK_CONFIDENCE,
            rationale="token_fallback",
            source="llm-fallback",
        )

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
