-- Cutover precondition: drain/stop the legacy collector before migration.
-- Fail rather than invalidate an in-flight legacy collection.
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM jobsearch.runs WHERE status='running') THEN
  RAISE EXCEPTION 'Drain existing collection runs before applying worker leases';
 END IF;
END $$;
ALTER TABLE jobsearch.runs ADD COLUMN IF NOT EXISTS worker_id text;
ALTER TABLE jobsearch.runs ADD COLUMN IF NOT EXISTS lease_token uuid;
ALTER TABLE jobsearch.runs ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz;
ALTER TABLE jobsearch.runs ADD COLUMN IF NOT EXISTS heartbeat_at timestamptz;
ALTER TABLE jobsearch.runs ADD COLUMN IF NOT EXISTS attempts integer NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS runs_expired_lease ON jobsearch.runs(lease_expires_at) WHERE status='running';
INSERT INTO jobsearch.schema_versions(version) VALUES(13) ON CONFLICT DO NOTHING;
