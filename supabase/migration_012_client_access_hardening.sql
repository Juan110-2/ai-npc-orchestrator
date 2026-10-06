-- =============================================================================
-- Migración 012 - Cerrar el acceso directo de los clientes a rol, métricas y vistas
--
-- Con la clave pública (anon) o con un usuario autenticado se puede hablar con
-- la base por la API de Supabase, sin pasar por el backend. Esta migración
-- cierra lo que quedaba expuesto por esa vía.
--
-- PROBLEMA:
--   1. El trigger handle_new_user() copiaba raw_user_meta_data->>'role' al
--      perfil. Ese metadato lo envía el cliente al registrarse, así que
--      cualquiera podía crear una cuenta con rol 'admin' o 'teacher'.
--   2. La política "user_profiles: editar propio perfil" permite UPDATE sobre
--      la fila propia sin limitar columnas, así que un usuario autenticado
--      podía cambiar su columna role desde el cliente.
--
-- SOLUCIÓN:
--   1. El trigger crea siempre el perfil con rol 'student'.
--   2. Los roles de cliente (anon, authenticated) solo pueden actualizar
--      full_name. El rol se cambia únicamente desde el backend
--      (PATCH /admin/users/{user_id}), que exige rol admin y se conecta con
--      el rol de base de datos del servidor, no con el del cliente.
--
--   3 y 4. Ver las secciones correspondientes más abajo.
--
-- No modifica ni borra filas existentes.
-- =============================================================================

-- 1. Alta de usuario: el rol inicial es siempre 'student'
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
        'student'
    )
    on conflict (id) do nothing;
    return new;
end;
$$;

-- 2. El cliente solo puede editar su nombre
revoke insert, update, delete on public.user_profiles from anon, authenticated;
grant update (full_name) on public.user_profiles to authenticated;

-- 3. ai_call_logs era la única tabla sin RLS: con la clave pública (anon) se
--    podía leer y escribir por la API de Supabase. Al activar RLS sin
--    políticas, los clientes quedan sin acceso; el backend no se ve afectado
--    porque su rol de conexión omite RLS, y el cliente web no consulta esta
--    tabla directamente (usa /admin/metrics/*).
alter table public.ai_call_logs enable row level security;

-- 4. Las vistas analíticas se ejecutan con los permisos de su dueño, por lo
--    que no aplican RLS, y los roles de cliente tenían SELECT sobre ellas.
--    v_student_evaluation_summary expone nombres, puntajes y retroalimentación.
--    Solo el backend las consulta, así que se retira el acceso a los clientes.
revoke all on public.v_provider_metrics           from anon, authenticated;
revoke all on public.v_session_metrics            from anon, authenticated;
revoke all on public.v_student_evaluation_summary from anon, authenticated;

-- =============================================================================
-- VERIFICACIÓN (ejecutar a mano después de aplicar)
--
-- a) Privilegios de columna: debe aparecer solo full_name para authenticated.
--    select grantee, column_name, privilege_type
--    from information_schema.column_privileges
--    where table_schema = 'public' and table_name = 'user_profiles'
--      and grantee in ('anon', 'authenticated') and privilege_type = 'UPDATE';
--
-- b) Revisar que los usuarios con rol elevado sean los esperados:
--    select email, role, created_at from public.user_profiles
--    where role <> 'student' order by created_at;
--
-- c) Las vistas no deben ser legibles por los clientes (ambas columnas en false):
--    select c.relname,
--           has_table_privilege('anon', c.oid, 'select') anon_sel,
--           has_table_privilege('authenticated', c.oid, 'select') auth_sel
--    from pg_class c
--    where c.relnamespace = 'public'::regnamespace and c.relkind = 'v';
--
-- REVERSIÓN:
--    grant insert, update, delete on public.user_profiles to anon, authenticated;
--    volver a crear handle_new_user() con
--    coalesce(new.raw_user_meta_data->>'role', 'student');
--    alter table public.ai_call_logs disable row level security;
--    grant select on public.v_provider_metrics, public.v_session_metrics,
--        public.v_student_evaluation_summary to anon, authenticated;
-- =============================================================================
-- FIN MIGRACIÓN 012
-- =============================================================================
