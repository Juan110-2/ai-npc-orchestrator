import time
from typing import Generator

from app.services.ai.base import AIClient, AIResponse, StreamResult

_MOCK_RESPONSES = [
    "No se. Me cuesta hablar de eso.",
    "Es que a veces siento que todo se junta y no se por donde empezar.",
    "Hoy fue un dia dificil, la verdad.",
    "Prefiero no pensar mucho en eso por ahora.",
    "No se si te lo puedo explicar bien, pero me siento agotada.",
]

# Respuestas que sirven como JSON valido para los servicios que esperan JSON.
_MOCK_CLASSIFIER_JSON = (
    '{"category": "neutral", "confidence": 0.55, "rationale": "mock"}'
)
_MOCK_EVALUATOR_JSON = (
    '{"empathy_score": 0.5, "assertiveness_score": 0.4,'
    ' "pressure_score": 0.1, "overall_impact": 0}'
)


class LocalMockAIClient(AIClient):
    """
    Simulacion sin IA real. Util para desarrollo local, pruebas unitarias
    y prototipado sin consumir tokens.

    Detecta heuristicamente el proposito de la llamada por el system_prompt
    (clasificador / evaluador / orquestador) y devuelve un payload coherente,
    para que los servicios que esperan JSON puedan parsear sin caer.
    """

    provider = "mock"
    model = "local-mock"

    def __init__(self) -> None:
        self._index = 0

    def _pick_response(self, system_prompt: str) -> str:
        text = (system_prompt or "").lower()
        if "clasificador de turnos" in text or '"category"' in text:
            return _MOCK_CLASSIFIER_JSON
        if "evaluador de intervenciones" in text or "empathy_score" in text:
            return _MOCK_EVALUATOR_JSON
        content = _MOCK_RESPONSES[self._index % len(_MOCK_RESPONSES)]
        self._index += 1
        return content

    def generate_response(
        self,
        system_prompt: str,
        user_prompt: str,
        context_messages: list[dict[str, str]] | None = None,
    ) -> AIResponse:
        content = self._pick_response(system_prompt)
        return AIResponse(
            content=content,
            provider=self.provider,
            model=self.model,
            tokens_input=0,
            tokens_output=0,
            latency_ms=0.0,
        )

    def generate_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        context_messages: list[dict[str, str]] | None = None,
    ) -> Generator[str, None, StreamResult]:
        content = self._pick_response(system_prompt)
        t0 = time.perf_counter()
        ttft_ms = 0.0
        first = True
        for word in content.split():
            if first:
                ttft_ms = (time.perf_counter() - t0) * 1000
                first = False
            yield word + " "
        return StreamResult(
            tokens_input=0,
            tokens_output=0,
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
            ttft_ms=round(ttft_ms, 2),
        )
