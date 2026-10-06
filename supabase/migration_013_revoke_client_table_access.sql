-- =============================================================================
-- Migración 013 - Retirar a los clientes el acceso directo a las tablas de datos
--
-- PROBLEMA:
--   El cliente web solo consulta directamente una cosa en Supabase: su propio
--   rol en user_profiles. Todo lo demás pasa por el backend. Aun así, los roles
--   de cliente (anon, authenticated) conservaban privilegios sobre el resto de
--   tablas y las políticas RLS permitían, por la API de Supabase y sin pasar
--   por el orquestador:
--     - reescribir o borrar los mensajes de una sesión propia y cambiar su
--       estado, severidad o tiempo (la evidencia con la que se evalúa);
--     - insertar sesiones a nombre de otro usuario (política
--       teacher_own_sessions, sin with check);
--     - crear perfiles y escenarios visibles para todos.
--
-- SOLUCIÓN:
--   1. Sin privilegios de cliente sobre las tablas de datos. El backend no se
--      ve afectado: se conecta con un rol propio que no depende de estos.
--   2. user_profiles: el cliente solo puede leer (RLS limita a su fila) y
--      editar full_name.
--   3. Las vistas pasan a ejecutarse con los permisos de quien consulta, para
--      que no vuelvan a quedar expuestas si se recrean.
--   4. Las tablas y vistas futuras no reciben privilegios de cliente por
--      defecto; si alguna debe ser legible desde el cliente, hay que otorgarlo
--      de forma explícita.
--
-- No modifica ni borra filas ni políticas existentes.
-- =============================================================================

-- 1. Tablas de datos: solo el backend
revoke all on public.sessions,
              public.conversation_messages,
              public.profiles,
              public.scenarios,
              public.session_evaluations,
              public.rubric_definitions,
              public.ai_call_logs
    from anon, authenticated;

-- 2. user_profiles: lectura de la fila propia y edición del nombre
revoke all on public.user_profiles from anon, authenticated;
grant select on public.user_profiles to authenticated;
grant update (full_name) on public.user_profiles to authenticated;

-- 3. Vistas con los permisos de quien consulta
alter view public.v_provider_metrics           set (security_invoker = true);
alter view public.v_session_metrics            set (security_invoker = true);
alter view public.v_student_evaluation_summary set (security_invoker = true);

-- 4. Objetos futuros sin privilegios de cliente por defecto
alter default privileges for role postgres in schema public
    revoke all on tables from anon, authenticated;

-- =============================================================================
-- VERIFICACIÓN (ejecutar a mano después de aplicar)
--
-- a) Ningún privilegio de cliente fuera de user_profiles (0 filas):
--    select table_name, grantee, privilege_type
--    from information_schema.role_table_grants
--    where table_schema = 'public' and grantee in ('anon', 'authenticated')
--      and table_name <> 'user_profiles';
--
-- b) El cliente no puede cambiar su rol (false) y sí su nombre (true):
--    select has_column_privilege('authenticated', 'public.user_profiles', 'role', 'UPDATE'),
--           has_column_privilege('authenticated', 'public.user_profiles', 'full_name', 'UPDATE');
--
-- REVERSIÓN:
--    grant all on public.sessions, public.conversation_messages, public.profiles,
--        public.scenarios, public.session_evaluations, public.rubric_definitions,
--        public.ai_call_logs to anon, authenticated;
--    alter view public.v_provider_metrics reset (security_invoker);  -- y las otras dos
--    alter default privileges for role postgres in schema public
--        grant all on tables to anon, authenticated;
-- =============================================================================
-- FIN MIGRACIÓN 013
-- =============================================================================
