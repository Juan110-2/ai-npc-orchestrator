from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.services.conversation.heuristics import HeuristicDecision


@dataclass(frozen=True)
class TurnContext:
    """Estado computado de un turno. Compartido entre converse y converse_stream."""

    decision: HeuristicDecision
    forced_close: bool
    closing: dict | None
    should_close: bool
    closing_kind: str | None
    context_history: list
    final_severity: float
    b_min: float
    b_max: float
    behavioral_flags: tuple[str, ...]
    # Datos para deshacer el turno si la IA falla (ver rollback_turn): id del
    # mensaje trainee guardado al inicio y severidad que tenia la sesion antes.
    trainee_msg_id: UUID | None = None
    previous_severity: float | None = None


@dataclass(frozen=True)
class StreamInputs:
    """Entradas preparadas para el generador SSE."""

    system_prompt: str | None
    effective_user_input: str
    forced_text: str | None


@dataclass
class StreamExecutionState:
    """Estado mutable del procesamiento streaming del mensaje del NPC."""

    accumulated: str = ""
    provider: str = "unknown"
    model: str = "unknown"
    tokens_input: int = 0
    tokens_output: int = 0
    latency_ms: float = 0.0
    ttft_ms: float = 0.0
    stream_error: Exception | None = None
