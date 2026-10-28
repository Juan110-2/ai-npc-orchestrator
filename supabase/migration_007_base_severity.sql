-- Migration 007: agrega base_severity a sessions
--
-- base_severity guarda la severidad inicial real de la sesión después de
-- aplicar el límite del perfil (min(scenario.severity, behavior_max)).
-- Permite que la lógica de cierre distinga si la sesión arrancó en el
-- límite máximo o mínimo del personaje, evitando cierres falsos.

-- La severidad de sesiones y mensajes pasa a decimal: el motor avanza en pasos
-- de 0.3, que no caben en un entero. En una base donde ya son float, estas dos
-- sentencias no cambian nada.
ALTER TABLE sessions ALTER COLUMN current_severity TYPE FLOAT USING current_severity::float;
ALTER TABLE conversation_messages ALTER COLUMN severity TYPE FLOAT USING severity::float;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS base_severity FLOAT;

-- Rellena las sesiones existentes con su current_severity actual como
-- mejor aproximación del valor inicial (no tenemos el historial exacto).
UPDATE sessions
SET base_severity = current_severity
WHERE base_severity IS NULL;
