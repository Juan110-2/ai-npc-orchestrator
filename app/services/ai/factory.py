from app.services.ai.local_mock import LocalMockAIClient
from app.services.ai.openai_client import OpenAIClient
from app.core.config import AI_PROVIDER

def get_ai_client():
    if AI_PROVIDER == "openai":
        return OpenAIClient()
    return LocalMockAIClient()
