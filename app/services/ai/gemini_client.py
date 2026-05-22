import time
from typing import Generator

import google.generativeai as genai
from google.generativeai.types import HarmBlockThreshold, HarmCategory

from app.core.config import GEMINI_API_KEY
from app.services.ai.base import AIClient, AIResponse, StreamResult

# Umbrales permisivos para simulación clínica (psicología / salud mental).
# Sin esto Gemini bloquea contenido terapéutico con finish_reason=SAFETY.
_CLINICAL_SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
}


def _safe_chunk_text(chunk) -> str | None:
    """Extrae texto de un chunk de streaming sin lanzar ValueError por safety blocks."""
    try:
        return chunk.text
    except (ValueError, AttributeError):
        return None


def _safe_response_text(response) -> str:
    """Extrae texto de una respuesta completa sin lanzar ValueError por safety blocks."""
    try:
        return response.text or ""
    except (ValueError, AttributeError):
        candidates = getattr(response, "candidates", [])
        if candidates and getattr(candidates[0], "content", None):
            parts = getattr(candidates[0].content, "parts", [])
            return "".join(getattr(p, "text", "") for p in parts)
        return ""


class GeminiClient(AIClient):
    """
    Cliente para la API de Google Gemini.
    Usa google-generativeai SDK. El modelo gemini-2.5-flash-lite es el equivalente
    a gpt-4o-mini en la linea de Gemini: rapido, economico y con buena calidad
    para tareas conversacionales.

    Notas:
    - A partir de google-generativeai >=0.5 se soporta `system_instruction` en
      `GenerativeModel`. Lo usamos para evitar el patron "user/model fake"
      que ensucia el conteo de turnos.
    - Los tokens se obtienen de response.usage_metadata.
    """

    provider = "gemini"
    model = "gemini-2.5-flash-lite"

    def __init__(self) -> None:
        genai.configure(api_key=GEMINI_API_KEY)
        self._generation_config = genai.GenerationConfig(
            max_output_tokens=260,
            temperature=0.3,
        )

    def _build_model_with_system(self, system_prompt: str):
        return genai.GenerativeModel(
            model_name=self.model,
            generation_config=self._generation_config,
            system_instruction=system_prompt,
            safety_settings=_CLINICAL_SAFETY_SETTINGS,
        )

    def _build_contents(
        self,
        user_prompt: str,
        context_messages: list[dict[str, str]] | None,
    ) -> list[dict]:
        contents: list[dict] = []
        if context_messages:
            for msg in context_messages:
                role = "user" if msg.get("role") == "user" else "model"
                contents.append({"role": role, "parts": [{"text": msg.get("content", "")}]})
        else:
            contents.append({"role": "user", "parts": [{"text": user_prompt}]})
        return contents

    def generate_response(
        self,
        system_prompt: str,
        user_prompt: str,
        context_messages: list[dict[str, str]] | None = None,
    ) -> AIResponse:
        model_instance = self._build_model_with_system(system_prompt)
        contents = self._build_contents(user_prompt, context_messages)

        t0 = time.perf_counter()
        response = model_instance.generate_content(contents)
        latency_ms = (time.perf_counter() - t0) * 1000

        content = _safe_response_text(response)
        usage = getattr(response, "usage_metadata", None)

        return AIResponse(
            content=content,
            provider=self.provider,
            model=self.model,
            tokens_input=usage.prompt_token_count if usage else 0,
            tokens_output=usage.candidates_token_count if usage else 0,
            latency_ms=round(latency_ms, 2),
        )

    def generate_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        context_messages: list[dict[str, str]] | None = None,
    ) -> Generator[str, None, StreamResult]:
        model_instance = self._build_model_with_system(system_prompt)
        contents = self._build_contents(user_prompt, context_messages)

        t0 = time.perf_counter()
        ttft_ms = 0.0
        first_chunk = True
        tokens_input = 0
        tokens_output = 0

        stream = model_instance.generate_content(contents, stream=True)
        for chunk in stream:
            text_part = _safe_chunk_text(chunk)
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
