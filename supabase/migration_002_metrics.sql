-- =============================================================================
-- Migracion 002 - Metricas tecnicas para seleccion de API de IA (Capitulo 3)
-- Proyecto: Trabajo de Grado - Universidad del Valle
-- Ejecutar en: Supabase Dashboard - SQL Editor - New Query
--
-- Esta migracion es ADITIVA. No modifica tablas existentes.
-- =============================================================================

-- =============================================================================
-- TABLA: ai_call_logs
-- Registro tecnico, verificable y reproducible de CADA llamada a una API de IA.
-- Independiente de la evaluacion pedagogica. Sirve para responder con datos:
-- "que proveedor responde mas rapido / es mas barato / falla menos / da JSON valido".
-- =============================================================================
create table if not exists public.ai_call_logs (
    id              uuid primary key default uuid_generate_v4(),

    -- Trazabilidad: a que sesion pertenece (puede ser NULL si la llamada
    -- es de un bench script o de un endpoint admin sin contexto de sesion)
    session_id      uuid references public.sessions(id) on delete set null,

    -- Proveedor / modelo usados en esta llamada
    provider        text not null,            -- "openai" | "gemini" | "deepseek" | "mock"
    model           text not null,

    -- Para que se uso: respuesta del NPC, clasificador, evaluador, bench
    purpose         text not null check (purpose in (
        'orchestrator', 'classifier', 'evaluator', 'bench', 'other'
    )),

    -- Modo: completo (sin streaming) o stream (token a token)
    call_mode       text not null default 'sync' check (call_mode in ('sync', 'stream')),

    -- Estado del resultado: ok, timeout, error de parseo, bloqueo de safety, etc.
    status          text not null check (status in (
        'ok', 'timeout', 'parse_error', 'safety_block',
        'rate_limit', 'auth_error', 'network_error', 'unknown_error'
    )),
    error_detail    text,

    -- Metricas de consumo (lo que devuelve el SDK del proveedor)
    tokens_input    integer,
    tokens_output   integer,

    -- Metricas de tiempo (en milisegundos)
    latency_ms      double precision,         -- tiempo total de la llamada
    ttft_ms         double precision,         -- time-to-first-token (solo en stream)

    -- Metricas de calidad de la respuesta
    json_valid      boolean,                  -- la respuesta era JSON valido (para classifier/evaluator)
    response_chars  integer,                  -- longitud del texto de respuesta (proxy de "cuanto contesto")
    prompt_chars    integer,                  -- longitud total del prompt enviado

    -- Costo estimado (usd) calculado contra pricing oficial
    cost_usd        double precision,

    -- Timestamp en UTC
    created_at      timestamptz not null default now()
);

comment on table public.ai_call_logs is
    'Log tecnico de cada llamada a una API de IA. Base de datos para la matriz comparativa del Capitulo 3 del TG.';
comment on column public.ai_call_logs.purpose is
    'orchestrator: respuesta del NPC | classifier: turn_classifier | evaluator: intervention_evaluator | bench: corrida de benchmarking comparativo | other: cualquier otra llamada experimental';
comment on column public.ai_call_logs.call_mode is
    'sync: chat.completions.create | stream: stream con stream_options.include_usage';
comment on column public.ai_call_logs.ttft_ms is
    'Time to first token. Solo se llena en call_mode=stream. Critico para percepcion de "tiempo real" en simulacion.';
comment on column public.ai_call_logs.json_valid is
    'TRUE si purpose en (classifier, evaluator) y la respuesta parseo como JSON valido. NULL si purpose=orchestrator (no aplica).';

-- =============================================================================
-- INDICES para consultas frecuentes
-- =============================================================================
create index if not exists idx_ai_call_logs_provider_purpose
    on public.ai_call_logs(provider, purpose, created_at desc);

create index if not exists idx_ai_call_logs_session
    on public.ai_call_logs(session_id) where session_id is not null;

create index if not exists idx_ai_call_logs_status
    on public.ai_call_logs(status) where status <> 'ok';

create index if not exists idx_ai_call_logs_created_at
    on public.ai_call_logs(created_at desc);

-- =============================================================================
-- VISTA: v_provider_metrics
-- Agregaciones por (proveedor, modelo, purpose) para alimentar 3.4 Matriz comparativa.
-- Calculadas SIEMPRE sobre ai_call_logs - no inventa nada.
-- =============================================================================
create or replace view public.v_provider_metrics as
select
    provider,
    model,
    purpose,
    count(*)                                                 as n_calls,
    count(*) filter (where status = 'ok')                    as n_ok,
    count(*) filter (where status <> 'ok')                   as n_errors,

    round(100.0 * count(*) filter (where status = 'ok') / nullif(count(*), 0), 2)
                                                             as success_rate_pct,

    -- Latencias (solo de calls OK, para no contaminar con timeouts)
    percentile_cont(0.50) within group (order by latency_ms)
        filter (where status = 'ok')                         as p50_latency_ms,
    percentile_cont(0.95) within group (order by latency_ms)
        filter (where status = 'ok')                         as p95_latency_ms,
    percentile_cont(0.99) within group (order by latency_ms)
        filter (where status = 'ok')                         as p99_latency_ms,
    avg(latency_ms) filter (where status = 'ok')             as mean_latency_ms,

    -- TTFT (solo streams)
    avg(ttft_ms) filter (where status = 'ok' and ttft_ms > 0)
                                                             as mean_ttft_ms,
    percentile_cont(0.95) within group (order by ttft_ms)
        filter (where status = 'ok' and ttft_ms > 0)         as p95_ttft_ms,

    -- Tokens
    avg(tokens_input)  filter (where status = 'ok')          as mean_tokens_input,
    avg(tokens_output) filter (where status = 'ok')          as mean_tokens_output,
    sum(tokens_input)  filter (where status = 'ok')          as total_tokens_input,
    sum(tokens_output) filter (where status = 'ok')          as total_tokens_output,

    -- Validez de JSON (solo para classifier/evaluator)
    round(100.0 * count(*) filter (where json_valid = true) /
          nullif(count(*) filter (where purpose in ('classifier','evaluator')), 0), 2)
                                                             as json_valid_rate_pct,

    -- Costo
    sum(cost_usd) filter (where status = 'ok')               as total_cost_usd,
    avg(cost_usd) filter (where status = 'ok')               as mean_cost_usd_per_call

from public.ai_call_logs
group by provider, model, purpose;

comment on view public.v_provider_metrics is
    'Agregaciones por proveedor/modelo/purpose. Fuente unica de verdad para la matriz comparativa del Capitulo 3.';

-- =============================================================================
-- RLS: ai_call_logs NO tiene RLS habilitada.
-- Razones:
--  1. La tabla no contiene datos personales del estudiante; solo telemetria
--     tecnica (provider, latencia, tokens, errores).
--  2. La proteccion de LECTURA esta en el endpoint /admin/metrics que valida
--     rol teacher/admin antes de devolver datos.
--  3. El INSERT viene del backend Python con SQLAlchemy. Habilitar RLS sin
--     politica de INSERT bloquea todos los logs (problema observado en pruebas).
-- =============================================================================
alter table public.ai_call_logs disable row level security;

-- =============================================================================
-- FIN MIGRACION 002
-- =============================================================================
