import os
from dotenv import load_dotenv

load_dotenv()

# ----- Base de datos --------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

# ----- Proveedor de IA activo -----------------------------------------------
# Valores validos: "openai" | "gemini" | "deepseek" | "mock"
# El valor por defecto es "mock" para no requerir keys en desarrollo local.
AI_PROVIDER = os.getenv("AI_PROVIDER", "mock")

VALID_PROVIDERS = {"openai", "gemini", "deepseek", "mock"}
if AI_PROVIDER not in VALID_PROVIDERS:
    raise ValueError(
        f"AI_PROVIDER='{AI_PROVIDER}' no es valido. "
        f"Valores aceptados: {', '.join(sorted(VALID_PROVIDERS))}"
    )

# ----- API Keys de proveedores ----------------------------------------------
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")
DEEPSEEK_API_KEY: str | None = os.getenv("DEEPSEEK_API_KEY")

# ----- Supabase Auth (opcional) ---------------------------------------------
SUPABASE_JWT_SECRET: str | None = os.getenv("SUPABASE_JWT_SECRET")
SUPABASE_URL: str | None = os.getenv("SUPABASE_URL")
SUPABASE_JWT_ISSUER: str | None = os.getenv("SUPABASE_JWT_ISSUER")
if not SUPABASE_JWT_ISSUER and SUPABASE_URL:
    SUPABASE_JWT_ISSUER = f"{SUPABASE_URL.rstrip('/')}/auth/v1"

SUPABASE_JWKS_URL: str | None = os.getenv("SUPABASE_JWKS_URL")
if not SUPABASE_JWKS_URL and SUPABASE_JWT_ISSUER:
    SUPABASE_JWKS_URL = f"{SUPABASE_JWT_ISSUER.rstrip('/')}/.well-known/jwks.json"

# ----- Validacion de key segun proveedor activo -----------------------------
_KEY_MAP = {
    "openai": ("OPENAI_API_KEY", OPENAI_API_KEY),
    "gemini": ("GEMINI_API_KEY", GEMINI_API_KEY),
    "deepseek": ("DEEPSEEK_API_KEY", DEEPSEEK_API_KEY),
}
if AI_PROVIDER in _KEY_MAP:
    env_name, key_value = _KEY_MAP[AI_PROVIDER]
    if not key_value:
        raise ValueError(
            f"El proveedor '{AI_PROVIDER}' requiere la variable de entorno '{env_name}'."
        )
