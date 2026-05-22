import time
from typing import Generator

from google import genai
from google.genai import types

from app.core.config import GEMINI_API_KEY
from app.services.ai.base import AIClient, AIResponse, StreamResult

_SAFETY_SETTINGS = [
    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_ONLY_HIGH"),
    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT",         threshold="BLOCK_ONLY_HIGH"),
    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH",        threshold="BLOCK_ONLY_HIGH"),
    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT",  threshold="BLOCK_ONLY_HIGH"),
]


class GeminiClient(AIClient):
    """
    Cliente para Google Gemini usando el SDK unificado google-genai.
    gemini-2.5-flash-lite: equivalente a gpt-4o-mini — rápido y económico.
    """

    provider = "gemini"
    model = "gemini-2.5-flash-lite"

    def __init__(self) -> None:
        self._client = genai.Client(api_key=GEMINI_API_KEY)

    def _config(self, system_prompt: str) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=260,
            temperature=0.3,
            safety_settings=_SAFETY_SETTINGS,
        )

    def _build_contents(
        self,
        user_prompt: str,
        context_messages: list[dict[str, str]] | None,
    ) -> list[dict]:
        if context_messages:
            return [
                {
                    "role": "user" if msg.get("role") == "user" else "model",
                    "parts": [{"text": msg.get("content", "")}],
                }
                for msg in context_messages
            ]
        return [{"role": "user", "parts": [{"text": user_prompt}]}]

    def generate_response(
        self,
        system_prompt: str,
        user_prompt: str,
        context_messages: list[dict[str, str]] | None = None,
    ) -> AIResponse:
        contents = self._build_contents(user_prompt, context_messages)

        _RETRY_DELAYS = (1.5, 3.0)
        last_exc: BaseException | None = None

        for attempt, delay in enumerate((_RETRY_DELAYS[0], _RETRY_DELAYS[1], None)):
            try:
                t0 = time.perf_counter()
                response = self._client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=self._config(system_prompt),
                )
                latency_ms = (time.perf_counter() - t0) * 1000
                break
            except Exception as exc:
                msg = str(exc).lower()
                is_overloaded = "503" in msg or "unavailable" in msg or "high demand" in msg
                if is_overloaded and delay is not None:
                    last_exc = exc
                    time.sleep(delay)
                    continue
                raise
        else:
            raise last_exc  # type: ignore[misc]

        try:
            content = response.text or ""
        except (ValueError, AttributeError):
            content = ""

        usage = getattr(response, "usage_metadata", None)
        return AIResponse(
            content=content,
            provider=self.provider,
            model=self.model,
            tokens_input=getattr(usage, "prompt_token_count", 0) or 0,
            tokens_output=getattr(usage, "candidates_token_count", 0) or 0,
            latency_ms=round(latency_ms, 2),
        )

    def generate_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        context_messages: list[dict[str, str]] | None = None,
    ) -> Generator[str, None, StreamResult]:
        contents = self._build_contents(user_prompt, context_messages)

        t0 = time.perf_counter()
        ttft_ms = 0.0
        first_chunk = True
        tokens_input = tokens_output = 0

        for chunk in self._client.models.generate_content_stream(
            model=self.model,
            contents=contents,
            config=self._config(system_prompt),
        ):
            try:
                text_part = chunk.text
            except (ValueError, AttributeError):
                text_part = None

            if text_part:
                if first_chunk:
                    ttft_ms = (time.perf_counter() - t0) * 1000
                    first_chunk = False
                yield text_part

            usage = getattr(chunk, "usage_metadata", None)
            if usage:
                tokens_input = getattr(usage, "prompt_token_count", 0) or tokens_input
                tokens_output = getattr(usage, "candidates_token_count", 0) or tokens_output

        latency_ms = (time.perf_counter() - t0) * 1000
        return StreamResult(
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            latency_ms=round(latency_ms, 2),
            ttft_ms=round(ttft_ms, 2),
        )
