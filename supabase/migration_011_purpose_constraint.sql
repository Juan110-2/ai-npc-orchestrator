-- =============================================================================
-- Migración 011 - Ampliar constraint de purpose en ai_call_logs
--
-- PROBLEMA:
--   El CHECK original solo aceptaba valores hardcodeados:
--   ('orchestrator','classifier','evaluator','bench','other')
--   Esto bloquea tags configurables como bench_v2, bench_refactor, etc.,
--   que los scripts de benchmark usan como purpose en log_ai_call().
--
-- SOLUCIÓN:
--   Reemplazar el CHECK por regex snake_case. La validación semántica
--   de qué valores son válidos sigue en ALLOWED_PURPOSES de metrics_logger.py.
-- =============================================================================

alter table public.ai_call_logs
    drop constraint if exists ai_call_logs_purpose_check;

alter table public.ai_call_logs
    add constraint ai_call_logs_purpose_check
    check (purpose ~ '^[a-z][a-z0-9_]{0,49}$');

-- =============================================================================
-- FIN MIGRACIÓN 011
-- =============================================================================
