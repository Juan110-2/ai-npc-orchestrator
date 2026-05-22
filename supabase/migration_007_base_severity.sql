-- Migration 007: agrega base_severity a sessions
--
-- base_severity guarda la severidad inicial real de la sesión después de
-- aplicar el límite del perfil (min(scenario.severity, behavior_max)).
-- Permite que la lógica de cierre distinga si la sesión arrancó en el
-- límite máximo o mínimo del personaje, evitando cierres falsos.

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS base_severity FLOAT;

-- Rellena las sesiones existentes con su current_severity actual como
-- mejor aproximación del valor inicial (no tenemos el historial exacto).
UPDATE sessions
SET base_severity = current_severity
WHERE base_severity IS NULL;
