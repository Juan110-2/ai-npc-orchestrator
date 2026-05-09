from typing import Generator

from app.services.ai.base import AIClient, AIResponse

_PROVIDER = "mock"
_MODEL = "local-mock"

_MOCK_RESPONSES = [
    "No sé… me cuesta hablar de eso.",
    "Es que a veces siento que todo se junta y no sé por dónde empezar.",
    "Hoy fue un día difícil, la verdad.",
    "Prefiero no pensar mucho en eso por ahora.",
    "No sé si te lo puedo explicar bien, pero me s