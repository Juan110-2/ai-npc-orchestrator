-- =============================================================================
-- Migración 010 - Corregir duration_minutes en las vistas de sesiones
--
-- PROBLEMA:
--   Ambas vistas calculaban duration_minutes como wall-clock
--   (ended_at - started_at), incluyendo tiempo idle, desconexiones y pausas.
--
-- SOLUCIÓN:
--   Usar sessions.accumulated_seconds (práctica efectiva reportada por el timer
--   del frontend) cuando está disponible. Fallback a wall-clock para sesiones
--   legacy o sin datos de timer.
--
-- NOTA TÉCNICA:
--   Se usa DROP + CREATE en lugar de CREATE OR REPLACE para evitar errores de
--   tipo/orden de columnas acumulados por ejecuciones anteriores fallidas.
--   Ninguna otra vista ni función depende de estas dos vistas.
-- =============================================================================

-- ── v_student_evaluation_summary ─────────────────────────────────────────────
drop view if exists public.v_student_evaluation_summary;

create view public.v_student_evaluation_summary as
select
    e.id                                              as evaluation_id,
    e.session_id,
    e.student_id,
    up.full_name                                      as student_name,
    e.status,
    s.started_at,
    s.ended_at,
    (e.automatic_metrics->>'turns_trainee')::integer  as turns_trainee,
    case
        when s.time_source in ('explicit', 'estimated')
             and coalesce(s.accumulated_seconds, 0) > 0
            then s.accumulated_seconds::float8 / 60.0
        when s.started_at is not null and s.ended_at is not null
            then extract(epoch from (s.ended_at - s.started_at)) / 60.0
        else null
    end                                               as duration_minutes,
    coalesce(s.time_source, 'none')                   as duration_source,
    (e.automatic_metrics->>'severity_final')::integer as severity_final,
    e.scores,
    e.teacher_feedback,
    e.submitted_at,
    e.created_at,
    e.updated_at
from public.session_evaluations e
left join public.sessions s on s.id = e.session_id
left join public.user_profiles up on up.id = e.student_id;

comment on view public.v_student_evaluation_summary is
    'Vista plana para evaluaciones. duration_minutes usa accumulated_seconds (práctica efectiva), no wall-clock.';


-- ── v_session_metrics ─────────────────────────────────────────────────────────
drop view if exists public.v_session_metrics;

create view public.v_session_metrics as
select
    s.id            as session_id,
    s.user_id,
    s.profile_id,
    s.scenario_id,
    s.started_at,
    s.ended_at,
    s.status,
    (s.ended_at is not null) as is_closed,
    case
        when s.ended_at is not null
             and s.time_source in ('explicit', 'estimated')
             and coalesce(s.accumulated_seconds, 0) > 0
            then s.accumulated_seconds::float8 / 60.0
        else
            extract(epoch from (coalesce(s.ended_at, now()) - s.started_at)) / 60.0
    end                      as duration_minutes,
    s.accumulated_seconds,
    s.time_source,
    count(cm.id) filter (where cm.role = 'trainee')          as trainee_turns,
    count(cm.id) filter (where cm.role = 'patient')          as patient_turns,
    max(cm.ai_provider) filter (where cm.role = 'patient')   as ai_provider,
    max(cm.ai_model)    filter (where cm.role = 'patient')   as ai_model,
    avg(cm.latency_ms)    filter (where cm.latency_ms    is not null) as avg_latency_ms,
    sum(cm.tokens_used)   filter (where cm.tokens_used   is not null) as total_tokens,
    sum(cm.tokens_input)  filter (where cm.tokens_input  is not null) as total_tokens_input,
    sum(cm.tokens_output) filter (where cm.tokens_output is not null) as total_tokens_output
from public.sessions s
left join public.conversation_messages cm on cm.session_id = s.id
group by s.id, s.user_id, s.profile_id, s.scenario_id,
         s.started_at, s.ended_at, s.status,
         s.accumulated_seconds, s.time_source;

comment on view public.v_session_metrics is
    'Métricas por sesión y proveedor. duration_minutes usa accumulated_seconds para sesiones cerradas con timer; wall-clock para sesiones abiertas o legacy.';

-- =============================================================================
-- FIN MIGRACIÓN 010
-- =============================================================================
