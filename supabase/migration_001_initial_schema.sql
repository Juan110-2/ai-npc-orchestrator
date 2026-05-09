-- =============================================================================
-- Migración 001 — Esquema inicial del Orquestador de IA para NPC
-- Proyecto: Trabajo de Grado — Universidad del Valle
-- Ejecutar en: Supabase Dashboard → SQL Editor → New Query
-- =============================================================================

-- ── Extensiones ───────────────────────────────────────────────────────────────
create extension if not exists "uuid-ossp";
create extension if not exists "pg_trgm";  -- búsqueda de texto, útil para logs

-- =============================================================================
-- TABLA: user_profiles
-- Extiende auth.users de Supabase con información del rol (estudiante/docente)
-- Se crea automáticamente cuando un usuario se registra (ver trigger al final)
-- =============================================================================
create table if not exists public.user_profiles (
    id          uuid primary key references auth.users(id) on delete cascade,
    email       text not null,
    full_name   text,
    role        text not null default 'student' check (role in ('student', 'teacher', 'admin')),
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

comment on table public.user_profiles is
    'Perfil extendido del usuario. El id referencia auth.users de Supabase.';
comment on column public.user_profiles.role is
    'student: practica con NPCs | teacher: configura casos y revisa resultados | admin: acceso total';

-- =============================================================================
-- TABLA: profiles
-- Perfiles de pacientes NPC: nombre, descripción clínica y rasgos de personalidad
-- =============================================================================
create table if not exists public.profiles (
    id          uuid primary key default uuid_generate_v4(),
    name        text not null,
    description text not null,
    traits      jsonb not null default '{}',
    created_by  uuid references public.user_profiles(id) on delete set null,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

comment on table public.profiles is
    'Perfiles de pacientes NPC. Cada perfil define la identidad del personaje simulado.';
comment on column public.profiles.traits is
    'Rasgos estructurados: { age, personality[], communication_style[], identity_name }';
comment on column public.profiles.created_by is
    'Usuario (docente) que creó el perfil. Null si fue creado sin auth activo.';

-- =============================================================================
-- TABLA: scenarios
-- Escenarios clínicos: contexto situacional, severidad inicial y restricciones
-- =============================================================================
create table if not exists public.scenarios (
    id          uuid primary key default uuid_generate_v4(),
    name        text not null,
    context     text not null,
    severity    integer not null check (severity between 0 and 5),
    risk_flags  jsonb not null default '[]',
    constraints jsonb not null default '{}',
    created_by  uuid references public.user_profiles(id) on delete set null,
    created_at  timestamptz not null default now()
);

comment on table public.scenarios is
    'Escenarios clínicos simulados. Define el contexto inicial de la sesión de práctica.';
comment on column public.scenarios.severity is
    'Severidad emocional inicial del NPC al comenzar la sesión (rango 0–5).';
comment on column public.scenarios.risk_flags is
    'Indicadores de riesgo activos: ["insomnio", "aislamiento", "crisis"]';
comment on column public.scenarios.constraints is
    '{ max_response_sentences, must_stay_in_character, allow_goodbye_when_calm }';

-- =============================================================================
-- TABLA: sessions
-- Sesiones de práctica clínica: vincula un estudiante, un perfil y un escenario
-- =============================================================================
create table if not exists public.sessions (
    id               uuid primary key default uuid_generate_v4(),
    profile_id       uuid not null references public.profiles(id) on delete restrict,
    scenario_id      uuid not null references public.scenarios(id) on delete restrict,
    user_id          uuid references public.user_profiles(id) on delete set null,
    current_severity integer not null check (current_severity between 0 and 5),
    started_at       timestamptz not null default now(),
    ended_at         timestamptz
);

comment on table public.sessions is
    'Sesiones de práctica. Cada sesión conecta un estudiante con un caso clínico simulado.';
comment on column public.sessions.user_id is
    'Estudiante que realizó la sesión. Null si fue creada sin auth activo.';
comment on column public.sessions.current_severity is
    'Severidad emocional actual del NPC (se actualiza turno a turno, rango 0–5).';

-- =============================================================================
-- TABLA: conversation_messages
-- Historial de conversación por sesión con métricas de IA por turno
-- =============================================================================
create table if not exists public.conversation_messages (
    id             uuid primary key default uuid_generate_v4(),
    session_id     uuid not null references public.sessions(id) on delete cascade,

    -- Contenido del turno
    role           text not null check (role in ('trainee', 'patient')),
    content        text not null,

    -- Estado emocional en el momento del turno
    severity       integer not null check (severity between 0 and 5),
    risk_flags     jsonb not null default '[]',

    -- Métricas de IA (solo se populan en mensajes del paciente)
    ai_provider    text,           -- "openai" | "gemini" | "deepseek" | "deterministic" | "mock"
    ai_model       text,           -- "gpt-4o-mini" | "gemini-1.5-flash" | "deepseek-chat" | etc.
    tokens_input   integer,
    tokens_output  integer,
    tokens_used    integer,        -- total = input + output
    latency_ms     float,          -- tiempo de respuesta de la API en milisegundos

    created_at     timestamptz not null default now()
);

comment on table public.conversation_messages is
    'Historial de conversación por sesión. Incluye métricas de IA para análisis comparativo.';
comment on column public.conversation_messages.role is
    'trainee: mensaje del estudiante | patient: respuesta del NPC generada por IA.';
comment on column public.conversation_messages.latency_ms is
    'Latencia real de la API de IA en ms. Usado para comparar proveedores en la tesis.';

-- =============================================================================
-- ÍNDICES para consultas frecuentes
-- =============================================================================
create index if not exists idx_sessions_user_id
    on public.sessions(user_id);

create index if not exists idx_sessions_profile_id
    on public.sessions(profile_id);

create index if not exists idx_sessions_ended_at
    on public.sessions(ended_at) where ended_at is null;  -- sesiones activas

create index if not exists idx_conv_messages_session_id
    on public.conversation_messages(session_id, created_at asc);

create index if not exists idx_conv_messages_ai_provider
    on public.conversation_messages(ai_provider) where ai_provider is not null;

create index if not exists idx_profiles_created_by
    on public.profiles(created_by);

-- =============================================================================
-- ROW LEVEL SECURITY (RLS)
-- El backend (FastAPI + SQLAlchemy) usa la connection string directa y
-- bypasea RLS. Las políticas aquí protegen acceso directo al cliente Supabase.
-- =============================================================================
alter table public.user_profiles     enable row level security;
alter table public.profiles          enable row level security;
alter table public.scenarios         enable row level security;
alter table public.sessions          enable row level security;
alter table public.conversation_messages enable row level security;

-- user_profiles: cada usuario ve y edita solo su propio perfil
create policy "user_profiles: ver propio perfil"
    on public.user_profiles for select
    using (auth.uid() = id);

create policy "user_profiles: editar propio perfil"
    on public.user_profiles for update
    using (auth.uid() = id);

-- profiles: todos los autenticados leen; solo el creador modifica
create policy "profiles: lectura autenticada"
    on public.profiles for select
    to authenticated
    using (true);

create policy "profiles: escritura solo creador"
    on public.profiles for all
    to authenticated
    using (created_by = auth.uid())
    with check (created_by = auth.uid());

-- scenarios: todos los autenticados leen; solo el creador modifica
create policy "scenarios: lectura autenticada"
    on public.scenarios for select
    to authenticated
    using (true);

create policy "scenarios: escritura solo creador"
    on public.scenarios for all
    to authenticated
    using (created_by = auth.uid())
    with check (created_by = auth.uid());

-- sessions: cada usuario ve solo sus propias sesiones
create policy "sessions: lectura propia"
    on public.sessions for select
    to authenticated
    using (user_id = auth.uid());

create policy "sessions: escritura propia"
    on public.sessions for all
    to authenticated
    using (user_id = auth.uid())
    with check (user_id = auth.uid());

-- conversation_messages: accesible si el usuario es dueño de la sesión
create policy "messages: acceso por sesión propia"
    on public.conversation_messages for all
    to authenticated
    using (
        exists (
            select 1 from public.sessions s
            where s.id = session_id
            and s.user_id = auth.uid()
        )
    );

-- =============================================================================
-- FUNCIÓN + TRIGGER: crear user_profile automáticamente al registrarse
-- Se ejecuta cada vez que un usuario se registra en Supabase Auth
-- =============================================================================
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
    insert into public.user_profiles (id, email, full_name, role)
    values (
        new.id,
        new.email,
        coalesce(new.raw_user_meta_data->>'full_name', split_part(new.email, '@', 1)),
        coalesce(new.raw_user_meta_data->>'role', 'student')
    )
    on conflict (id) do nothing;
    return new;
end;
$$;

create or replace trigger on_auth_user_created
    after insert on auth.users
    for each row execute procedure public.handle_new_user();

-- =============================================================================
-- FUNCIÓN: updated_at automático
-- =============================================================================
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create trigger set_profiles_updated_at
    before update on public.profiles
    for each row execute procedure public.set_updated_at();

create trigger set_user_profiles_updated_at
    before update on public.user_profiles
    for each row execute procedure public.set_updated_at();

-- =============================================================================
-- VISTA: métricas de sesiones por proveedor (útil para comparativa de tesis)
-- =============================================================================
create or replace view public.v_session_metrics as
select
    s.id                                        as session_id,
    s.user_id,
    s.profile_id,
    s.scenario_id,
    s.started_at,
    s.ended_at,
    (s.ended_at is not null)                    as is_closed,
    extract(epoch from (coalesce(s.ended_at, now()) - s.started_at)) / 60
                                                as duration_minutes,
    count(cm.id) filter (where cm.role = 'trainee')  as trainee_turns,
    count(cm.id) filter (where cm.role = 'patient')  as patient_turns,
    cm.ai_provider,
    cm.ai_model,
    avg(cm.latency_ms) filter (where cm.latency_ms is not null)  as avg_latency_ms,
    sum(cm.tokens_used) filter (where cm.tokens_used is not null) as total_tokens,
    sum(cm.tokens_input) filter (where cm.tokens_input is not null) as total_tokens_input,
    sum(cm.tokens_output) filter (where cm.tokens_output is not null) as total_tokens_output
from public.sessions s
left join public.conversation_messages cm on cm.session_id = s.id
group by s.id, s.user_id, s.profile_id, s.scenario_id,
         s.started_at, s.ended_at, cm.ai_provider, cm.ai_model;

comment on view public.v_session_metrics is
    'Métricas agregadas por sesión y proveedor de IA. Usada para análisis comparativo en la tesis.';

-- =============================================================================
-- DATOS DE PRUEBA (comentar en producción)
-- Un perfil y escenario de ejemplo para validar la configuración
-- =============================================================================
/*
insert into public.profiles (name, description, traits) values (
    'Valentina Rojas',
    'Estudiante universitaria de 21 años con sobrecarga académica y ansiedad anticipatoria.',
    '{
        "age": 21,
        "personality": ["reservada", "sensible", "perfeccionista"],
        "communication_style": ["responde breve", "se abre con empatía"],
        "identity_name": "Valentina Rojas"
    }'
);

insert into public.scenarios (name, context, severity, risk_flags, constraints) values (
    'Sobrecarga académica en universidad',
    'La paciente acaba de salir de clase, se siente cansada y con miedo a fallar.',
    3,
    '["insomnio", "aislamiento reciente"]',
    '{
        "max_response_sentences": 3,
        "must_stay_in_character": true,
        "allow_goodbye_when_calm": true
    }'
);
*/

-- =============================================================================
-- FIN DE MIGRACIÓN
-- Verificar ejecución correcta con:
--   select table_name from information_schema.tables
--   where table_schema = 'public' order by table_name;
-- =============================================================================
