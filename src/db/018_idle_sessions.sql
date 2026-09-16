-- Idle sessions. A signed-in account that is not an administrator is signed out after
-- settings.idle_minutes without an authenticated request, in every product that authenticates
-- through this service (Job Search, Job Prep, the Library). last_seen_at is when the session
-- was last used: src/api/main.py reads it on every authenticated request, deletes the row and
-- answers 401 when it is older than the limit, and writes a fresh stamp only when the one it
-- read has gone stale, so an active session is not a write on every request.
--
-- Sessions that already exist start from now, so nobody is signed out by the migration itself.
ALTER TABLE jobsearch.sessions ADD COLUMN IF NOT EXISTS last_seen_at timestamptz NOT NULL DEFAULT now();
INSERT INTO jobsearch.schema_versions(version) VALUES(18) ON CONFLICT DO NOTHING;
