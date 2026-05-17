-- Migration 008: Add status column to sessions
-- Replaces the previous pattern of deriving status from ended_at IS NULL.
-- States: active | completed | terminated
-- 'terminated' means the session was force-closed (crisis or inappropriate conduct).

ALTER TABLE sessions
  ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active';

-- Backfill existing rows: open sessions → active, closed sessions → completed
UPDATE sessions
SET status = CASE
  WHEN ended_at IS NULL THEN 'active'
  ELSE 'completed'
END;
