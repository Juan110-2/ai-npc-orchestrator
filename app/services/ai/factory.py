from app.core.config import AI_PROVIDER
from app.services.ai.base import AIClient


def get_ai_client() -> AIClient:
    """
    Factory de clientes de IA.
    El proveedor activo se controla con la variable de entorno AI_PROVIDER.
    La validación del valor ya ocurre en c