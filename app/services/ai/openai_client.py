import time
from typing import Generator

from openai import OpenAI

from app.core.config import OPENAI_API_KEY
from app.services.ai.base import AIClient, AIResponse, StreamResult


class OpenAIClient(AIClient):
    """
    Cliente para la API de OpenAI.
    Modelo: gpt-4o-mini (balance calidad/costo para MVP).
    Implementa generate_response (completo) y generate_stream (SSE) con metricas reales.
    """

    provider = "openai"
    model = "gpt-4o-mini"

    def __init__(self) -> None:
        # timeout por intento para no colgar el endpoint si OpenAI tarda. Con el reintento
        # debe caber en PARALLEL_TIMEOUT_S (20 s); si no, el resultado del reintento se pierde.
        self.client = OpenAI(api_key=OPENAI_API_KEY, timeout=8.0, max_retries=1)

    def _build_messages(
        self,
        system_prompt: str,
        user_prompt: str,
        context_messages: list[dict[str, str]] | None,
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        if context_messages:
            messages.extend(context_messages)
        else:
            messages.append({"role": "user", "content": user_prompt})
        return messages

    def generate_response(
        self,
        system_prompt: str,
        user_prompt: str,
        context_messages: list[dict[str, str]] | None = None,
    ) -> AIResponse:
        messages = self._build_messages(system_prompt, user_prompt, context_messages)

        t0 = time.perf_counter()
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=260,
            temperature=0.3,
        )
        latency_ms = (time.perf_counter() - t0) * 1000

        usage = response.usage
        return AIResponse(
            content=response.choices[0].message.content or "",
            provider=self.provider,
            model=self.model,
            tokens_input=usage.prompt_tokens if usage else 0,
            tokens_output=usage.completion_tokens if usage else 0,
            latency_ms=round(latency_ms, 2),
        )

    def generate_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        context_messages: list[dict[str, str]] | None = None,
    ) -> Generator[str, None, StreamResult]:
        """
        Stream con metricas reales. Devuelve StreamResult via StopIteration.value
        cuando el generator termina. Activa stream_options.include_usage para
        que OpenAI envie el bloque usage en el ultimo chunk.
        """
        messages = self._build_messages(system_prompt, user_prompt, context_messages)

        t0 = time.perf_counter()
        ttft_ms = 0.0
        first_chunk = True
        tokens_input = 0
        tokens_output = 0

        stream = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=260,
            temperature=0.3,
            stream=True,
            stream_options={"include_usage": True},
        )
        for chunk in stream:
            # El chunk final con usage no trae choices
            if chunk.choices:
                delta = chunk.choices[0].delta.content
                if delta:
                    if first_chunk:
                        ttft_ms = (time.perf_counter() - t0) * 1000
                        first_chunk = False
                    yield delta
            usage = getattr(chunk, "usage", None)
            if usage:
                tokens_input = getattr(usage, "prompt_tokens", 0) or 0
                tokens_output = getattr(usage, "completion_tokens", 0) or 0

        latency_ms = (time.perf_counter() - t0) * 1000
        return StreamResult(
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            latency_ms=round(latency_ms, 2),
            ttft_ms=round(ttft_ms, 2),
        )
