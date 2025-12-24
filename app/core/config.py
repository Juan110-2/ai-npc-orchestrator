import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

# AI configuration
AI_PROVIDER = os.getenv("AI_PROVIDER", "mock")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")