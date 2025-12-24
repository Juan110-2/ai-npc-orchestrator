import json
from app.services.ai.factory import get_ai_client


def evaluate_intervention(user_input: str) -> dict:
    """
    Evalúa la calidad de la intervención del aprendiz.
    NO genera texto visible.
    """

    prompt = f"""
    Eres un evaluador de intervenciones en un entorno de formación en psicología.

    Analiza el mensaje del estudiante y determina su impacto probable
    en la regulación emocional de un paciente vulnerable, no seas tan técnico.
    Que la evolución sea práctica, no compliques tanto el bajar el puntaje.

    CRITERIOS OBLIGATORIOS:
    - Si el mensaje muestra escucha, validación emocional o apertura,
    el impacto DEBE ser -1.
    - Si el mensaje es neutro o informativo sin carga emocional,
    el impacto DEBE ser 0.
    - Si el mensaje es directivo, presionante o invalidante,
    el impacto DEBE ser 1.

    Mensaje del estudiante:
    "{user_input}"

    Devuelve SOLO un JSON válido con:
    - empathy_score (0 a 1)
    - assertiveness_score (0 a 1)
    - pressure_score (0 a 1)
    - overall_impact (-1, 0 o 1)

    No expliques nada.
    No agregues texto.
    """

    ai = get_ai_client()
    raw_response = ai.generate_response(prompt, "")
    return json.loads(raw_response)
