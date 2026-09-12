ALTER TABLE jobsearch.users ADD COLUMN IF NOT EXISTS password_hash text;
CREATE TABLE IF NOT EXISTS jobsearch.login_limits (
 bucket text PRIMARY KEY, attempts integer NOT NULL DEFAULT 0,
 window_start timestamptz NOT NULL DEFAULT now()
);
INSERT INTO jobsearch.schema_versions(version) VALUES(2) ON CONFLICT DO NOTHING;
