ALTER TABLE jobsearch.runs ADD COLUMN IF NOT EXISTS decision_counts jsonb;
ALTER TABLE jobsearch.runs ADD COLUMN IF NOT EXISTS trace_id text;
INSERT INTO jobsearch.schema_versions(version) VALUES(3) ON CONFLICT DO NOTHING;
