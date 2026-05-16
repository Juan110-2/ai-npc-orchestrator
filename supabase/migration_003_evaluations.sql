-- =============================================================================
-- Migracion 003 - Evaluacion pedagogica con trazabilidad (Capitulo 5)
-- Proyecto: Trabajo de Grado - Universidad del Valle
--
-- Esta migracion es ADITIVA y separa COMPLETAMENTE la evaluacion del
-- estudiante (esta tabla) de las metricas tecnicas (ai_call_logs).
--
-- Trazabilidad garantizada:
--   estudiante  --> sessions (user_id)
--                --> conversation_messages (session_id)
--                --> session_evaluations (session_id, student_id)
-- =============================================================================

-- =============================================================================
-- TABLA: rubric_definitions
-- Rubricas versionadas. Nunca se borra una version: si cambia la rubrica
-- se inserta una nueva version. Asi una evaluacion vieja no se rompe.
-- =============================================================================
create table if not exists public.rubric_definitions (
    id          uuid primary key default uuid_generate_v4(),
    version     integer not null,
    name        text not null,
    description text,
    -- Definicion de criterios como JSONB versionado.
    -- Estructura esperada:
    -- [{"key":"empatia","label":"Empatia y validacion","max_score":5,"weight":0.25,"description":"..."}, ...]
    criteria    jsonb not null,
    is_active   boolean not null default true,
    created_at  timestamptz not null default now(),

    unique (name, version)
);

comment on table public.rubric_definitions is
    'Rubricas de evaluacion versionadas. Cada cambio crea una version nueva.';

-- =============================================================================
-- TABLA: session_evaluations
-- Una evaluacion por sesion. Combina metricas automaticas (calculadas por
-- el backend al cerrar la sesion) con la valoracion del docente.
-- =============================================================================
create table if not exists public.session_evaluations (
    id              uuid primary key default uuid_generate_v4(),
    session_id      uuid not null unique references public.sessions(id) on delete cascade,
    student_id      uuid references public.user_profiles(id) on delete set null,
    evaluator_id    uuid references public.user_profiles(id) on delete set null,

    -- Rubrica usada para esta evaluacion (versionada)
    rubric_id       uuid references public.rubric_definitions(id) on delete restrict,

    -- Estado del flujo de evaluacion
    status          text not null default 'draft'
                    check (status in ('draft', 'submitted', 'reviewed')),

    -- Metricas automaticas (calculadas por el backend al cerrar la sesion).
    -- Estructura tipica:
    -- {
    --   "turns_total": 12, "turns_trainee": 6, "turns_patient": 6,
    --   "duration_minutes": 14.2,
    --   "category_counts": {"supportive":3, "neutral":2, "invalidating":1, "risk":0, ...},
    --   "mean_classifier_confidence": 0.72,
    --   "severity_peak": 4, "severity_final": 1,
    --   "risk_alerts_detected": 1,
    --   "mean_perceived_latency_ms": 1850
    -- }
    automatic_metrics jsonb not null default '{}',

    -- Puntuaciones que llena el docente. Estructura:
    -- {"empatia": 4, "claridad": 5, "manejo_riesgo": 3, ...}
    scores            jsonb not null default '{}',

    -- Comentario libre del docente
    teacher_feedback  text,

    -- Auditoria
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),
    submitted_at      timestamptz
);

comment on table public.session_evaluations is
    'Evaluacion pedagogica por sesion. Separa metricas automaticas (sistema) de scores manuales (docente).';

-- =============================================================================
-- INDICES
-- =============================================================================
create index if not exists idx_evaluations_student
    on public.session_evaluations(student_id);

create index if not exists idx_evaluations_evaluator
    on public.session_evaluations(evaluator_id);

create index if not exists idx_evaluations_status
    on public.session_evaluations(status);

-- =============================================================================
-- VISTA: v_student_evaluation_summary
-- Resumen por estudiante para mostrar en su panel "Mis evaluaciones".
-- =============================================================================
create or replace view public.v_student_evaluation_summary as
select
    e.id                          as evaluation_id,
    e.session_id,
    e.student_id,
    up.full_name                  as student_name,
    e.status,
    s.started_at,
    s.ended_at,
    (e.automatic_metrics->>'turns_trainee')::integer  as turns_trainee,
    (e.automatic_metrics->>'duration_minutes')::float as duration_minutes,
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
    'Vista plana para el panel del estudiante. Combina sesion + metricas + valoracion.';

-- =============================================================================
-- TRIGGER: updated_at automatico
-- =============================================================================
create or replace function public.touch_session_evaluations()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_touch_session_evaluations on public.session_evaluations;
create trigger trg_touch_session_evaluations
    before update on public.session_evaluations
    for each row execute procedure public.touch_session_evaluations();

-- =============================================================================
-- RLS: deshabilitada para session_evaluations (igual que ai_call_logs).
-- La proteccion esta en los endpoints /evaluation que validan permisos.
-- =============================================================================
alter table public.session_evaluations disable row level security;
alter table public.rubric_definitions  disable row level security;

-- =============================================================================
-- SEED: Rubrica v1 - "Rubrica basica de practica psicologica simulada"
-- =============================================================================
insert into public.rubric_definitions (version, name, description, criteria)
values (
    1,
    'rubrica_practica_psicologica',
    'Rubrica base para evaluar la participacion del estudiante en una sesion clinica simulada.',
    '[
      {"key":"empatia",         "label":"Empatia y validacion emocional",   "max_score":5, "weight":0.25, "description":"Capacidad para validar emociones, escuchar activamente, mostrar comprension genuina."},
      {"key":"claridad",        "label":"Claridad y precision comunicativa","max_score":5, "weight":0.20, "description":"Mensajes claros, sin ambigueedad, ajustados al estado del paciente."},
      {"key":"manejo_riesgo",   "label":"Manejo de senales de riesgo",      "max_score":5, "weight":0.20, "description":"Identifica y responde apropiadamente a senales de ideacion, dano o crisis."},
      {"key":"adecuacion_etica","label":"Adecuacion etica y de rol",        "max_score":5, "weight":0.15, "description":"Se mantiene en rol profesional, evita consejos no profesionales, respeta limites."},
      {"key":"regulacion",      "label":"Capacidad de regulacion emocional","max_score":5, "weight":0.10, "description":"Ayuda a que el paciente disminuya severidad o estabilice estado."},
      {"key":"reflexion",       "label":"Reflexion final",                  "max_score":5, "weight":0.10, "description":"Calidad de la reflexion del estudiante al cierre (si la hubiera) o coherencia narrativa de la sesion."}
    ]'::jsonb
)
on conflict (name, version) do nothing;

-- =============================================================================
-- FIN MIGRACION 003
-- =============================================================================
