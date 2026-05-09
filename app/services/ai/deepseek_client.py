import time
from typing import Generator

from openai import OpenAI

from app.core.config import DEEPSEEK_API_KEY
from app.services.ai.base import AIClient, AIResponse

_PROVIDER = "deepseek"
_MODEL = "deepseek-chat"
_BASE_URL = "https://api.deepseek.com"


class DeepSeekClient(AIClient):
    """
    Cliente para la API de DeepSeek.
    DeepSeek expone una API compatible con el SDK de OpenAI — solo cambia
    base_url y modelo. deepseek-chat es el modelo de propósito general
    con mejor relación calidad/costo del proveedor.
    """

    def __init__(self) -> None:
        self.client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=_BASE_URL,
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
            model=_MODEL,
            messages=messages,
            max_tokens=260,
            temperature=0.3,
        )
        latency_ms = (time.perf_counter() - t0) * 1000

        usage = response.usage
        return AIResponse(
            content=response.choices[0].message.content or "",
            provider=_PROVIDER,
            model=_MODEL,
            tokens_input=usage.prompt_tokens if usage else 0,
            tokens_output=usage.completion_tokens if usage else 0,
            latency_ms=round(latency_ms, 2),
        )

    def generate_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        context_messages: list[dict[str, str]] | None = None,
    ) -> Generator[str, None, None]:
        messages = self._build_messages(system_prompt, user_prompt, context_messages)

        stream = self.client.chat.completions.create(
            model=_MODEL,
            messages=messages,
            max_tokens=260,
            temperature=0.3,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
