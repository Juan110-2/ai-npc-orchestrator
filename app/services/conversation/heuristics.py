from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
import unicodedata
from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.services.conversation.classifier import TurnClassifier
from app.repositories.conversation_repository import ConversationRepository

# Patrones normalizados (sin tildes, minúsculas) de insultos directos y lenguaje agresivo.
# Se compila una sola vez a nivel de módulo para no penalizar cada turno.
# Todos los patrones operan sobre texto ya normalizado (_normalize elimina tildes).
# Criterio de inclusión: el patrón debe ser inequívoco en contexto terapéutico; se
# excluyen palabras con uso coloquial ambiguo para evitar falsos positivos.
_ABUSE_RE = re.compile(
    # Insultos personales directos
    r"\bidiota\b"
    r"|\bestupid[ao]\b"
    r"|\bimbecil\b"
    r"|\bmalparido\b"
    r"|\bhijueputa\b"
    r"|\bhijoepu\w*\b"
    r"|\bhijuemadre\b"
    r"|\bpendejo\b"
    r"|\bgilipollas\b"
    r"|\bsubnormal\b"
    r"|\bretrasad[ao]\b"
    r"|\bcabron\b"
    # "puta" standalone eliminado: demasiado ambiguo en español coloquial.
    # "inutil" standalone eliminado: cubierto por el compuesto "eres un inutil".
    # Descalificaciones directas
    r"|\bno sirves\b"
    r"|\bno vales\b"
    r"|\beres (un |una )?(mierda|basura|idiota|estupid[ao]|imbecil|pendejo|inutil)\b"
    r"|\beres (una? )?(porqueria|basura)\b"
    # Comandos hostiles / rechazo agresivo
    r"|\bcallate?\b"
    r"|\bcallese\b"
    r"|\bcierra (la |tu )?boca\b"
    r"|\blargate?\b"
    r"|\bjodete\b"
    r"|\bvete al carajo\b"
    r"|\bvete a la mierda\b"
    r"|\bvete al diablo\b"
    r"|\bque te jodan\b"
    # "me importa/vale una mierda" — desdén explícito hacia la persona
    r"|\bme (importa|vale) (una? )?mierda\b"
    # "no me importas" — 2ª persona, claramente dirigido a la persona; "no me importa"
    # (sin 's') es demasiado ambiguo ("no me importa el tema") para incluirlo solo.
    r"|\bno me importas\b"
    # Abandono hostil del vínculo terapéutico
    r"|\bdejame en paz\b"
    r"|\bdejame tranquil[ao]\b"
    r"|\bno quiero (hablar contigo|escucharte|verte)\b"
)

# Etiquetas retóricas al final de una frase ("¿verdad?", "¿no?", etc.).
# Requieren al menos un espacio o coma antes para no capturar el inicio del texto.
_RHETORICAL_TAG_RE = re.compile(
    r"[,\s]+[¿]?\s*"
    r"(?:verdad|no es cierto|no|cierto|ok|okey|de acuerdo|entiendes?|me\s+sigues?|me\s+entiendes?)"
    r"\s*\?",
    re.IGNORECASE,
)

# Pronombre interrogativo al inicio de cláusula SIN signos de pregunta.
# Excluye "que" y "cual": demasiado ambiguos en español sin soporte de signos.
# Requiere al menos 2 caracteres de contenido tras el pronombre para ser substantiva.
_CLAUSE_QUESTION_RE = re.compile(
    r"(?:^|[.!,;]\s*)"
    r"\b(como|por\s*que|cuando|donde|quien(?:es)?|cuanto(?:[sa]s?)?)\b"
    r"(?=\s+\w{2,})",
    re.IGNORECASE,
)


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
    next_severity: float
    should_close: bool
    should_rotate_focus: bool
    response_mode: ResponseMode
    max_sentences: int
    matched_rules: Tuple[str, ...] = field(default_factory=tuple)


class ConversationHeuristics:
    """Reglas rápidas y determinísticas para clasificar un turno y ajustar estado."""

    MIN_SEVERITY = 0   # 0 = paciente calmado, sesión puede cerrar
    MAX_SEVERITY = 5   # 5 = crisis, sesión cierra automáticamente
    _ABUSE_HISTORY_WINDOW = 10  # Turnos recientes del trainee a revisar para reincidencia

    def __init__(self) -> None:
        self.turn_classifier = TurnClassifier()

    def decide(
        self,
        user_text: str,
        current_severity: float,
        *,
        db: Optional[Session] = None,
        session_id: Optional[UUID] = None,
        current_msg_id: Optional[UUID] = None,
    ) -> HeuristicDecision:
        normalized = self._normalize(user_text)
        is_abuse = self._is_explicit_abuse(normalized)
        has_question = self._has_open_question(user_text)

        category, matched_rules, confidence = self._classify(
            normalized, db=db, session_id=session_id
        )
        category, matched_rules, confidence = self._apply_category_overrides(
            category, matched_rules, confidence, user_text, is_abuse
        )

        repeat_abuse = False
        if is_abuse and db is not None and session_id is not None:
            try:
                recent = ConversationRepository.list_recent_by_session(
                    db=db,
                    session_id=session_id,
                    limit=self._ABUSE_HISTORY_WINDOW * 2,
                )
                # Excluir el mensaje actual: reincidencia = 2+ abusos previos, no
                # "mensaje actual + uno anterior". Si current_msg_id no se provee
                # (llamada legacy), el conteo puede incluir el mensaje actual — es
                # aceptable como comportamiento conservador.
                prior_trainee = [
                    m for m in recent
                    if getattr(m, "role", "") == "trainee"
                    and (current_msg_id is None or m.id != current_msg_id)
                ]
                abuse_count = sum(
                    1 for m in prior_trainee
                    if self._is_explicit_abuse(
                        self._normalize(getattr(m, "content", "") or "")
                    )
                )
                repeat_abuse = abuse_count >= 2
            except Exception:
                pass

        return self._apply_rules(
            category,
            current_severity,
            matched_rules,
            has_question=has_question,
            repeat_abuse=repeat_abuse,
        )

    @staticmethod
    def prepare_inputs(user_text: str) -> tuple[str, bool]:
        """
        Normaliza y detecta abuso léxico en un solo paso.
        Interfaz pública para que el router pueda pre-computar antes de lanzar hilos.
        Retorna (normalized, is_abuse).
        """
        normalized = ConversationHeuristics._normalize(user_text)
        return normalized, ConversationHeuristics._is_explicit_abuse(normalized)

    def classify(
        self,
        normalized_text: str,
        *,
        db: Optional[Session] = None,
        session_id: Optional[UUID] = None,
    ) -> Tuple[MessageCategory, Tuple[str, ...], float]:
        """Clasifica semánticamente texto ya normalizado. Interfaz pública de _classify."""
        return self._classify(normalized_text, db=db, session_id=session_id)

    def decide_from_parts(
        self,
        user_text: str,
        current_severity: float,
        *,
        semantic_result: Optional[Tuple[MessageCategory, Tuple[str, ...], float]] = None,
        is_abuse: bool = False,
        repeat_abuse: bool = False,
    ) -> HeuristicDecision:
        """
        Aplica overrides determinísticos y reglas de negocio sobre resultados pre-computados.
        Diseñado para el flujo paralelo del router; no realiza ninguna llamada I/O.
        semantic_result = (category, matched_rules, confidence) devuelto por _classify().
        Si es None (tarea semántica falló), usa el fallback estructural.
        """
        normalized = self._normalize(user_text)
        has_question = self._has_open_question(user_text)

        if semantic_result is not None:
            category, matched_rules, confidence = semantic_result
        else:
            # Fallback sin I/O cuando la tarea semántica no devolvió resultado.
            matched_rules: Tuple[str, ...] = ("fallback:no_semantic",)
            if not normalized or len(normalized) <= 2:
                category, confidence = MessageCategory.CONFUSING, 0.4
            elif not any(c.isalpha() for c in normalized):
                category, confidence = MessageCategory.CONFUSING, 0.4
            else:
                category, confidence = MessageCategory.NEUTRAL, 0.5

        category, matched_rules, confidence = self._apply_category_overrides(
            category, matched_rules, confidence, user_text, is_abuse
        )

        return self._apply_rules(
            category,
            current_severity,
            matched_rules,
            has_question=has_question,
            repeat_abuse=repeat_abuse,
        )

    def _classify(
        self,
        normalized_text: str,
        *,
        db: Optional[Session] = None,
        session_id: Optional[UUID] = None,
    ) -> Tuple[MessageCategory, Tuple[str, ...], float]:
        if not normalized_text:
            return MessageCategory.CONFUSING, ("empty_message",), 0.0

        semantic = self.turn_classifier.classify(
            normalized_text, db=db, session_id=session_id
        )
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

    @staticmethod
    def _apply_category_overrides(
        category: MessageCategory,
        matched_rules: Tuple[str, ...],
        confidence: float,
        user_text: str,
        is_abuse: bool,
    ) -> Tuple[MessageCategory, Tuple[str, ...], float]:
        """
        Overrides determinísticos compartidos por decide() y decide_from_parts().
        Orden garantizado: múltiples preguntas primero, abuso siempre gana.
        """
        if category == MessageCategory.SUPPORTIVE and ConversationHeuristics._count_questions(user_text) >= 3:
            category = MessageCategory.CONFUSING
            matched_rules = matched_rules + ("override:multiple_questions",)
            confidence = 0.5

        if is_abuse:
            category = MessageCategory.INAPPROPRIATE
            matched_rules = matched_rules + ("override:explicit_abuse",)
            confidence = 1.0

        return category, matched_rules, confidence

    def _apply_rules(
        self,
        category: MessageCategory,
        current_severity: float,
        matched_rules: Tuple[str, ...],
        has_question: bool = False,
        repeat_abuse: bool = False,
    ) -> HeuristicDecision:
        severity = self._clamp(current_severity)

        next_severity = severity
        should_close = False
        should_rotate_focus = False
        response_mode = ResponseMode.NEUTRAL
        max_sentences = 3

        if category == MessageCategory.SUPPORTIVE:
            # La heurística ya NO baja la severidad automáticamente.
            # El evaluador de intervenciones (IA paralela) es quien decide si
            # el apoyo fue lo suficientemente bueno para reducirla (-1) o no (0).
            # Así se requiere calidad sostenida, no solo intención positiva.
            next_severity = severity
            response_mode = ResponseMode.EMPATHIC
            # Pregunta abierta real: el paciente tiene más para decir en respuesta.
            max_sentences = 4 if has_question else 3

        elif category == MessageCategory.INDIFFERENT:
            # La indiferencia no contiene: con malestar medio-alto tiende a empeorar.
            next_severity = self._clamp(severity + 0.5 if severity >= 3 else severity)
            response_mode = ResponseMode.DEFENSIVE if severity >= 3 else ResponseMode.CLARIFY
            max_sentences = 2

        elif category == MessageCategory.NEUTRAL:
            next_severity = severity
            response_mode = ResponseMode.NEUTRAL
            # Pregunta abierta real: el paciente tiene más para decir en respuesta.
            max_sentences = 4 if has_question else 3

        elif category == MessageCategory.CONFUSING:
            # has_question no amplía max_sentences aquí: si el mensaje fue clasificado
            # como confuso, el paciente responde brevemente para pedir aclaración, sin
            # importar si contenía un signo de pregunta.
            next_severity = severity
            should_rotate_focus = True
            response_mode = ResponseMode.CLARIFY
            max_sentences = 2

        elif category == MessageCategory.INVALIDATING:
            next_severity = self._clamp(severity + 0.5)
            response_mode = ResponseMode.DEFENSIVE
            max_sentences = 2

        elif category == MessageCategory.INAPPROPRIATE:
            if repeat_abuse:
                # Abuso reiterado: penalización severa y cierre por trato inadecuado.
                next_severity = self._clamp(severity + 2.0)
                should_close = True
                response_mode = ResponseMode.BOUNDARY
                max_sentences = 1
                matched_rules = matched_rules + ("recurrence:repeat_abuse",)
            else:
                # Primera agresión directa: límite claro, sin respuesta complaciente.
                # +1.0 es más fuerte que invalidación común (+0.5) para diferenciarlos.
                next_severity = self._clamp(severity + 1.0)
                should_rotate_focus = True
                response_mode = ResponseMode.BOUNDARY
                max_sentences = 2

        elif category == MessageCategory.RISK:
            next_severity = self._clamp(max(severity + 0.5, 4.0))
            response_mode = ResponseMode.CRISIS
            max_sentences = 2
            if severity >= 4:
                should_close = True

        # Cierre por deterioro máximo: al llegar al pico de severidad con un turno adverso,
        # se termina la sesión para representar "peor escenario" de forma controlada.
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
    def _is_explicit_abuse(normalized_text: str) -> bool:
        """Detecta insultos directos, descalificaciones o lenguaje agresivo explícito."""
        return bool(_ABUSE_RE.search(normalized_text))

    @staticmethod
    def _count_questions(text: str) -> int:
        """Cuenta signos de interrogación de cierre para detectar múltiples preguntas."""
        return text.count("?")

    @staticmethod
    def _has_open_question(user_input: str) -> bool:
        """
        Detecta si el input del entrenador contiene una pregunta abierta substantiva.
        Dos caminos:
          1. Con '?'/'¿': elimina etiquetas retóricas al final; confirma si queda
             una pregunta real con al menos 2 palabras.
          2. Sin signos: busca pronombre interrogativo al inicio de cláusula seguido
             de contenido (≥2 chars). Excluye 'que'/'cual' por ambigüedad en español.
        """
        text = user_input.strip()

        if "?" in text or "¿" in text:
            cleaned = _RHETORICAL_TAG_RE.sub("", text).strip()
            # Si tras quitar etiquetas retóricas no queda ningún signo de pregunta,
            # la pregunta era puramente retórica (ej.: "entiendo, ¿no?").
            if "?" not in cleaned and "¿" not in cleaned:
                return False
            # Preguntas de una sola palabra ("¿no?", "¿sí?") no son substantivas.
            return len(cleaned.split()) >= 2

        # Sin signos de interrogación: solo aceptar pronombre interrogativo al inicio
        # de cláusula y con contenido posterior real.
        normalized = ConversationHeuristics._normalize(text)
        return bool(_CLAUSE_QUESTION_RE.search(normalized))

    @staticmethod
    def _normalize(text: str) -> str:
        normalized = (text or "").strip().lower()
        normalized = unicodedata.normalize("NFKD", normalized)
        normalized = "".join(c for c in normalized if not unicodedata.combining(c))
        # Captura variantes como "perrrra" sin usar fuzzy matching costoso.
        normalized = re.sub(r"([a-z])\1{2,}", r"\1\1", normalized)
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized

    def _clamp(self, value) -> float:
        return max(float(self.MIN_SEVERITY), min(float(self.MAX_SEVERITY), float(value)))
