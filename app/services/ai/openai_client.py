from openai import OpenAI
from app.services.ai.base import AIClient
from app.core.config import OPENAI_API_KEY

class OpenAIClient(AIClient):

    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY)

    def generate_response(
        self,
        system_prompt: str,
        user_prompt: str,
        context_messages: list[dict[str, str]] | None = None,
    ) -> str:
        messages = [{"role": "system", "content": system_prompt}]

        if context_messages:
            messages.extend(context_messages)
        else:
            messages.append({"role": "user", "content": user_prompt})

        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=260,
            temperature=0.3
        )

        return response.choices[0].message.content
