"""
Tarifas oficiales de los proveedores de IA al momento de las pruebas
(Mayo 2026). Usadas para calcular costo estimado por llamada y poblar
ai_call_logs.cost_usd. Quedan en codigo para reproducibilidad academica.

Formato: USD por 1 millon de tokens (estandar de la industria).
Si el proveedor cambia precios, actualizar aca y dejar registro del cambio.

Fuentes:
- OpenAI: https://openai.com/api/pricing/
- Google Gemini: https://ai.google.dev/pricing
- DeepSeek: https://api-docs.deepseek.com/quick_start/pricing/
"""

# USD por 1M de tokens (input, output)
PRICING_PER_MILLION_TOKENS: dict[str, dict[str, dict[str, float]]] = {
    "openai": {
       "gpt-4o-mini": {"input": 0.150, "output": 0.600},
    },
    "gemini": {
        "gemini-2.5-flash-lite": {"input": 0.100, "output": 0.400},
    },
    "deepseek": {
        "deepseek-v4-flash": {"input": 0.140, "output": 0.280},
    },
    "mock": {
        "local-mock": {"input": 0.0, "output": 0.0},
    },
}


def estimate_cost_usd(
    provider: str,
    model: str,
    tokens_input: int,
    tokens_output: int,
) -> float | None:
    """
    Devuelve el costo estimado en USD para una llamada con N tokens de input
    y M tokens de output. None si no hay tarifa registrada.
    """
    pricing = PRICING_PER_MILLION_TOKENS.get(provider, {}).get(model)
    if not pricing:
        return None
    cost = (
        (tokens_input or 0)  / 1_000_000 * pricing["input"]
        + (tokens_output or 0) / 1_000_000 * pricing["output"]
    )
    return round(cost, 8)
