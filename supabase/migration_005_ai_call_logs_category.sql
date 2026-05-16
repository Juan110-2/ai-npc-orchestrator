-- =============================================================================
-- Migracion 005 - Categoria del clasificador en ai_call_logs
-- Proyecto: Trabajo de Grado - Universidad del Valle
--
-- Esta migracion es ADITIVA. No modifica datos existentes.
-- =============================================================================

alter table public.ai_call_logs
  add column if not exists category text;

comment on column public.ai_call_logs.category is
    'Categoria detectada por el clasificador (supportive, neutral, invalidating, etc). Solo aplica cuando purpose=classifier.';

create index if not exists idx_ai_call_logs_category
    on public.ai_call_logs(category)
    where category is not null;

-- =============================================================================
-- FIN MIGRACION 005
-- =============================================================================
