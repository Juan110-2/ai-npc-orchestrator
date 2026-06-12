"""
Evaluador de intervenciones del estudiante.
Si se pasa `db`, registra cada llamada a IA en ai_call_logs (purpose='evaluator').
Sin db, sigue funcionando para compatibilidad con tests.
"""
import json
import re
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.services.ai.factory import get_ai_client
from app.services.ai.metrics_logger import log_ai_call

_DEFAULT_RESULT: dict = {
    "empathy_score": 0.0,
    "assertiveness_score": 0.0,
    "pressure_score": 0.0,
    "overall_impact": 0,
}


def _default_result() -> dict:
    return dict(_DEFAULT_RESULT)


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    text = text.strip()
    try:
        loaded = json.loads(text)
        if isinstance(loaded, dict):
            return loaded
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            loaded = json.loads(match.group(0))
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            return None
    return None


def _build_prompt(user_input: str) -> str:
    return f"""
    Eres un evaluador de intervenciones en un entorno de formacion en psicologia.

    Analiza el mensaje del estudiante y determina su impacto probable
    en la regulacion emocional de un paciente vulnerable, no seas tan tecnico.
    Que la evolucion sea practica, no compliques tanto el bajar el puntaje.

    CRITERIOS OBLIGATORIOS:
    - Si el mensaje muestra escucha, validacion emocional o apertura,
    el impacto DEBE ser -1.
    - Si el mensaje es neutro o informativo sin carga emocional,
    el impacto DEBE ser 0.
    - Si el mensaje es directivo, presionante o invalidante,
    el impacto DEBE ser 1.

    Mensaje del estudiante:
    "{user_input}"

    Devuelve SOLO un JSON valido con:
    - empathy_score (0 a 1)
    - assertiveness_score (0 a 1)
    - pressure_score (0 a 1)
    - overall_impact (-1, 0 o 1)

    No expliques nada. No agregues texto.
    """


def _sanitize(parsed: dict) -> dict:
    result = _default_result()
    for key in ("empathy_score", "assertiveness_score", "pressure_score"):
        try:
            result[key] = max(0.0, min(1.0, float(parsed.get(key, 0.0))))
        except Exception:
            result[key] = 0.0
    try:
        impact = int(parsed.get("overall_impact", 0))
        result["overall_impact"] = max(-1, min(1, impact))
    except Exception:
        result["overall_impact"] = 0
    return result


def _parse_evaluation_response(content: str) -> tuple[dict, bool]:
    parsed = _extract_json(content)
    if not parsed:
        return _default_result(), False
    return _sanitize(parsed), True


def _evaluate_with_client(ai, prompt: str) -> dict:
    ai_response = ai.generate_response(prompt, "")
    result, _ = _parse_evaluation_response(ai_response.content)
    return result


def evaluate_intervention(
    user_input: str,
    *,
    db: Optional[Session] = None,
    session_id: Optional[UUID] = None,
) -> dict:
    """
    Devuelve siempre un dict con las claves esperadas. Si el proveedor falla
    o el JSON es invalido, devuelve resultado neutro (overall_impact=0).
    Si se pasa `db`, registra la llamada en ai_call_logs.
    """
    prompt = _build_prompt(user_input)

    if db is not None:
        with log_ai_call(db, purpose="evaluator", session_id=session_id) as ctx:
            ctx.record_prompt_chars(len(prompt))
            try:
                ai_response = ctx.client.generate_response(prompt, "")
                result, is_valid_json = _parse_evaluation_response(ai_response.content)
                if not is_valid_json:
                    ctx.record_parse_error(ai_response.content)
                    return _default_result()
                ctx.record_response(ai_response, json_valid=True)
                return result
            except Exception as exc:
                ctx.record_error(exc)
                return _default_result()

    # Fallback sin logging (compatibilidad / tests sin BD)
    try:
        ai = get_ai_client()
        return _evaluate_with_client(ai, prompt)
    except Exception:
        return _default_result()
