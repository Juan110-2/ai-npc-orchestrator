from openai import OpenAI
from app.services.ai.base import AIClient
from app.core.config import OPENAI_API_KEY

class OpenAIClient(AIClient):

    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY)

    def generate_response(self, system_prompt: str, user_prompt: str) -> str:
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=260,
            temperature=0.3
        )

        return response.choices[0].message.content
