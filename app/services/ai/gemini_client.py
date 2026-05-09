import time
from typing import Generator

import google.generativeai as genai

from app.core.config import GEMINI_API_KEY
from app.services.ai.base import AIClient, AIResponse

_PROVIDER = "gemini"
_MODEL = "gemini-1.5-flash"


class GeminiClient(AIClient):
    """
    Cliente para la API de Google Gemini.
    Usa google-generativeai SDK. El modelo gemini-1.5-flash es el equivalente
    a gpt-4o-mini en la línea de Gemini: rápido, económico y con buena calidad
    para tareas conversacionales.

    Adaptación de contrato:
    - Gemini no separa system_prompt como rol independiente en todos sus modelos.
      Se inyecta como primer turno de usuario con instrucción explícita,
      seguido del historial y el mensaje actual. Esto mantiene coherencia de rol.
    - Los tokens se obtienen de response.usage_metadata.
    """

    def __init__(self) -> None:
        genai.configure(api_key=GEMINI_API_KEY)
        self.model = genai.GenerativeModel(
            model_name=_MODEL,
            generation_config=genai.GenerationConfig(
                max_output_tokens=260,
                temperature=0.3,
            ),
        )

    def _build_contents(
        self,
        system_prompt: str,
        user_prompt: str,
        context_messages: list[dict[str, str]] | None,
    ) -> list[dict]:
        """
        Construye el historial de contenidos para Gemini.
        El system_prompt se inyecta como primer mensaje del modelo (role=model)
        precedido de una instrucción de rol en el primer turno de usuario.
        Esto es el patrón recomendado para modelos Gemini que no soportan
        system_instruction en todas las versiones del SDK.
        """
        contents = []

        # Inyección del system prompt como contexto inicial de rol
        contents.append({
            "role": "user",
            "parts": [{"text": f"[INSTRUCCIÓN DE SISTEMA — NO RESPONDAS ESTO, SOLO ADOPTA EL ROL]\n{system_prompt}"}],
        })
        contents.append({
            "role": "model",
            "parts": [{"text": "Entendido. Asumo el rol indicado."}],
        })

        # Historial de conversación previo
        if context_messages:
            for msg in context_messages:
                role = "user" if msg.get("role") == "user" else "model"
                contents.append({
                    "role": role,
                    "parts": [{"text": msg.get("content", "")}],
                })

        # Turno actual del usuario
        contents.append({
            "role": "user",
            "parts": [{"text": user_prompt}],
        })

        return contents

    def generate_response(
        self,
        system_prompt: str,
        user_prompt: str,
        context_messages: list[dict[str, str]] | None = None,
    ) -> AIResponse:
        contents = self._build_contents(system_prompt, user_prompt, context_messages)

        t0 = time.perf_counter()
        response = self.model.generate_content(contents)
        latency_ms = (time.perf_counter() - t0) * 1000

        content = response.text or ""
        usage = response.usage_metadata

        return AIResponse(
            content=content,
            provider=_PROVIDER,
            model=_MODEL,
            tokens_input=usage.prompt_token_count if usage else 0,
            tokens_output=usage.candidates_token_count if usage else 0,
            latency_ms=round(latency_ms, 2),
        )

    def generate_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        context_messages: list[dict[str, str]] | None = None,
    ) -> Generator[str, None, None]:
        contents = self._build_contents(system_prompt, user_prompt, context_messages)

        stream = self.model.generate_content(contents, stream=True)
        for chunk in stream:
            if chunk.text:
                yield chunk.text
