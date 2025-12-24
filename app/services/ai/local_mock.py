from app.services.ai.base import AIClient

class LocalMockAIClient(AIClient):
    """
    Simulación sin IA real.
    Útil para pruebas, mundo 3D y prototipado.
    """

    def generate_response(self, system_prompt: str, user_prompt: str) -> str:
        return "No sé… me cuesta hablar de eso."
