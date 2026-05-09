import time
from typing import Generator

from openai import OpenAI

from app.core.config import OPENAI_API_KEY
from app.services.ai.base import AIClient, AIResponse

_PROVIDER = "openai"
_MODEL = "gpt-4o-mini"


class OpenAIClient(AIClient):
    """
    Cliente para la API de OpenAI.
    Modelo: gpt-4o-mini (balance calidad/costo para MVP).
    Implementa generate_response (completo) y generate_stream (SSE).
    """

    def __init__(self) -> None:
        self.client = OpenAI(api_key=OPENAI_API_KEY)

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
            messages.ap