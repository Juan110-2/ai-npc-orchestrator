from functools import lru_cache

from app.core.config import AI_PROVIDER
from app.services.ai.base import AIClient


@lru_cache(maxsize=4)
def _build_client(provider: str) -> AIClient:
    """Construye el cliente una sola vez por proveedor; reutiliza conexiones HTTP."""
    if provider == "openai":
        from app.services.ai.openai_client import OpenAIClient
        return OpenAIClient()
    if provider == "gemini":
        from app.services.ai.gemini_client import GeminiClient
        return GeminiClient()
    if provider == "deepseek":
        from app.services.ai.deepseek_client import DeepSeekClient
        return DeepSeekClient()
    from app.services.ai.local_mock import LocalMockAIClient
    return LocalMockAIClient()


def get_ai_client(provider: str | None = None) -> AIClient:
    """
    Factory de clientes de IA con singleton por proveedor.
    El proveedor activo se controla con AI_PROVIDER, pero tambien puede
    pasarse explicitamente (util para benchmarking de los 3 proveedores).

    Proveedores disponibles:
      - "openai"   -> OpenAIClient   (gpt-4o-mini)
      - "gemini"   -> GeminiClient   (gemini-1.5-flash)
      - "deepseek" -> DeepSeekClient (deepseek-chat)
      - "mock"     -> LocalMockAIClient (sin IA real)
    """
    return _build_client(provider or AI_PROVIDER)
