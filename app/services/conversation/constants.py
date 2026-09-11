MAX_CLOSING_TURNS = 3
EVALUATOR_SCALE = 0.3
ABUSE_HISTORY_WINDOW = 10
PARALLEL_TIMEOUT_S = 20.0
MAX_RESPONSE_CHARS = 8_000
HISTORY_LIMIT = 10

# NOTA: la instruccion de despedida por closing_kind ("CLOSING_INSTR") se quito
# de aqui. Se probo que el LLM la ignora la mayoria de las veces sin importar el
# tipo de cierre, asi que el turno final ahora se genera SIN esa instruccion (como
# un turno normal) y la despedida garantizada se concatena aparte -- ver
# ConversationOrchestrator._CLOSING_TAILS / ensure_closing_tail en orchestrator.py.
