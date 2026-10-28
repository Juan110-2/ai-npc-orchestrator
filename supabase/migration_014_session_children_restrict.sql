-- =============================================================================
-- Migración 014 - Mensajes y evaluaciones ya no se borran en cascada con la sesión
--
-- PROBLEMA:
--   conversation_messages.session_id y session_evaluations.session_id estaban
--   definidas con ON DELETE CASCADE (migraciones 001 y 003). Borrar una sesión
--   por cualquier vía (SQL manual, un cambio futuro del backend, el panel de
--   Supabase) arrastraba en silencio todo su historial: la evidencia con la que
--   se evalúa al estudiante.
--
-- SOLUCIÓN:
--   Cambiar ambas FK a ON DELETE RESTRICT. Postgres rechaza borrar una sesión que
--   tenga mensajes o evaluación. El backend (DELETE /profiles y /scenarios) solo
--   borra sesiones sin uso, tras bloquearlas con FOR UPDATE y comprobar que no
--   tienen mensajes, evaluaciones ni registros de IA; esta migración es la
--   segunda barrera, en la base.
--
-- ai_call_logs.session_id NO se modifica: sigue en ON DELETE SET NULL, porque
-- es un registro técnico (métricas de costo y latencia) que debe sobrevivir a la
-- sesión.
--
-- Los nombres de las restricciones son los que Postgres asigna por defecto a las
-- FK declaradas en línea. Es idempotente (drop ... if exists) y no modifica filas.
-- =============================================================================

begin;

alter table public.conversation_messages
    drop constraint if exists conversation_messages_session_id_fkey;
alter table public.conversation_messages
    add constraint conversation_messages_session_id_fkey
    foreign key (session_id) references public.sessions(id) on delete restrict;

alter table public.session_evaluations
    drop constraint if exists session_evaluations_session_id_fkey;
alter table public.session_evaluations
    add constraint session_evaluations_session_id_fkey
    foreign key (session_id) references public.sessions(id) on delete restrict;

commit;

-- =============================================================================
-- VERIFICACIÓN (solo lectura, tras aplicar):
--   select conname, confdeltype      -- 'r' = restrict, 'c' = cascade, 'n' = set null
--   from pg_constraint
--   where conname in ('conversation_messages_session_id_fkey',
--                     'session_evaluations_session_id_fkey',
--                     'ai_call_logs_session_id_fkey');
--   -- Esperado: r, r y n.
--
-- REVERSIÓN:
--   alter table public.conversation_messages
--       drop constraint conversation_messages_session_id_fkey,
--       add constraint conversation_messages_session_id_fkey
--           foreign key (session_id) references public.sessions(id) on delete cascade;
--   alter table public.session_evaluations
--       drop constraint session_evaluations_session_id_fkey,
--       add constraint session_evaluations_session_id_fkey
--           foreign key (session_id) references public.sessions(id) on delete cascade;
-- =============================================================================
-- FIN MIGRACIÓN 014
-- =============================================================================
