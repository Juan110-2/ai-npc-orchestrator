-- Migration 006: Add assigned_by and assigned_at to sessions
-- assigned_by: teacher/admin who created or assigned the session
-- assigned_at: timestamp of the assignment

ALTER TABLE public.sessions
    ADD COLUMN IF NOT EXISTS assigned_by  uuid REFERENCES public.user_profiles(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS assigned_at  timestamptz DEFAULT now();

-- Backfill: for existing sessions, best-effort
UPDATE public.sessions
SET assigned_by = user_id,
    assigned_at = started_at
WHERE assigned_by IS NULL AND user_id IS NOT NULL;

-- Index for teacher-scoped listing
CREATE INDEX IF NOT EXISTS idx_sessions_assigned_by ON public.sessions(assigned_by);

-- Update RLS: teacher sees sessions they assigned; student sees their own; admin sees all
DROP POLICY IF EXISTS "teacher_own_sessions" ON public.sessions;
CREATE POLICY "teacher_own_sessions" ON public.sessions
    FOR ALL
    USING (
        auth.uid() = assigned_by
        OR auth.uid() = user_id
        OR EXISTS (
            SELECT 1 FROM public.user_profiles
            WHERE id = auth.uid() AND role = 'admin'
        )
    );