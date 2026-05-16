-- =============================================================================
-- Migración 004 — Fusión de "protopersona" dentro de profiles.behavior
-- Proyecto: Trabajo de Grado — Universidad del Valle
--
-- Esta migración es ADITIVA. No modifica datos existentes. Solo añade una
-- columna JSONB para guardar el comportamiento conversacional del paciente
-- (disparadores, reguladores, rango de severidad, reacciones por tipo de
-- intervención). Antes se manejaba en una "protopersona" aparte; ahora vive
-- dentro del perfil mismo.
-- =============================================================================

alter table public.profiles
  add column if not exists behavior jsonb not null default '{}';

comment on column public.profiles.behavior is
    'Comportamiento conversacional del paciente: { triggers[], regulators[], '
    'behavior_min, behavior_max, reactions{ supportive, invalidating, ... }, '
    'closure_rules[] }. Reemplaza la entidad "protopersona" del frontend.';

-- =============================================================================
-- FIN MIGRACIÓN 004
-- =============================================================================
