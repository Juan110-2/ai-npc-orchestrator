MAX_CLOSING_TURNS = 3
EVALUATOR_SCALE = 0.3
ABUSE_HISTORY_WINDOW = 10
PARALLEL_TIMEOUT_S = 20.0
MAX_RESPONSE_CHARS = 8_000
HISTORY_LIMIT = 10

CLOSING_INSTR: dict[str, str] = {
    "success": (
        "La conversacion ha logrado calmarte. Despidete agradeciendo de manera "
        "concreta por la ayuda recibida sobre tu situacion especifica "
        "(mencionala brevemente). Expresa alivio real y un cierre amable. "
        "No introduzcas problemas nuevos."
    ),
    "crisis": (
        "Estas en crisis emocional intensa (severidad 5). No puedes sostener "
        "mas la conversacion. Despidete brevemente mencionando que tu situacion "
        "concreta te tiene desbordado y que necesitas parar ahora. "
        "Tono breve, emocional, sin agresividad."
    ),
    "inappropriate": (
        "El usuario te trato de manera inadecuada y vas a cerrar la conversacion "
        "con dignidad. Despidete brevemente marcando un limite claro y firme. "
        "Sin agresividad, pero con firmeza. Una o dos frases maximo."
    ),
}
