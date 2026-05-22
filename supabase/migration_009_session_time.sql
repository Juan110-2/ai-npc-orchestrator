-- Migration 009: Session time tracking
-- accumulated_seconds: total confirmed practice time (from explicit timer or estimated)
-- time_source: quality/origin of the time datum
--   'none'        → session still active, no data yet
--   'explicit'    → frontend timer reported at least one delta flush
--   'estimated'   → backend computed from message gaps at close time
--   'unavailable' → session closed with no messages and no timer
-- last_interaction_at: timestamp of last flush or message (used for display / analytics)

ALTER TABLE sessions
  ADD COLUMN IF NOT EXISTS accumulated_seconds INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS time_source VARCHAR(20) NOT NULL DEFAULT 'none',
  ADD COLUMN IF NOT EXISTS last_interaction_at TIMESTAMP WITH TIME ZONE;

-- Backfill: all existing closed sessions have no time data → unavailable
-- (can't compute estimates retroactively without a separate Python script)
UPDATE sessions
  SET time_source = 'unavailable'
  WHERE ended_at IS NOT NULL;
