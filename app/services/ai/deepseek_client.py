import time
from typing import Generator

from openai import OpenAI

from app.core.config import DEEPSEEK_API_KEY
from app.services.ai.base import AIClient, AIResponse, StreamResult


class DeepSeekClient(AIClient):
    """
    Cliente para la API de DeepSeek.
    DeepSeek expone una API compatible con el SDK de OpenAI: solo cambia
    base_url y modelo. DeepSeek-V4-Flash es el modelo de proposito general
    con mejor relacion calidad/costo del proveedor.
    """

    provider = "deepseek"
    model = "deepseek-v4-flash"
    _BASE_URL = "https://api.deepseek.com"

    def __init__(self) -> None:
        self.client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=self._BASE_URL,
            timeout=20.0,
            max_retries=1,
        )

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
            # DeepSeek cuenta el razonamiento interno del modelo contra el
            # mismo limite de max_tokens que la respuesta visible. Con 260
            # (el valor usado por los demas proveedores, que no razonan) el
            # razonamiento agotaba el presupuesto antes de emitir texto
            # visible, dejando respuestas vacias o cortadas a mitad de
            # palabra. El margen extra cubre ese razonamiento sin cambiar la
            # longitud objetivo de la respuesta visible (~260 tokens).
            max_tokens=1024,
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
        messages = self._build_messages(system_prompt, user_prompt, context_messages)

        t0 = time.perf_counter()
        ttft_ms = 0.0
        first_chunk = True
        tokens_input = 0
        tokens_output = 0

        stream = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            # Ver comentario en generate_response: el razonamiento interno
            # comparte presupuesto con la respuesta visible.
            max_tokens=1024,
            temperature=0.3,
            stream=True,
            stream_options={"include_usage": True},
        )
        for chunk in stream:
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
