CREATE TABLE IF NOT EXISTS jobsearch.private_intake (
 user_id bigint PRIMARY KEY REFERENCES jobsearch.users(id) ON DELETE CASCADE,
 payload bytea NOT NULL, version uuid NOT NULL, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS jobsearch.private_resume (
 user_id bigint NOT NULL REFERENCES jobsearch.users(id) ON DELETE CASCADE,
 variant text NOT NULL CHECK(variant IN ('default','capital_one')),
 payload bytea NOT NULL, version uuid NOT NULL, updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(user_id,variant)
);
CREATE TABLE IF NOT EXISTS jobsearch.private_applications (
 user_id bigint NOT NULL REFERENCES jobsearch.users(id) ON DELETE CASCADE,
 job_id uuid NOT NULL REFERENCES jobsearch.jobs(id), payload bytea NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(user_id,job_id)
);
ALTER TABLE jobsearch.private_intake ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobsearch.private_intake FORCE ROW LEVEL SECURITY;
ALTER TABLE jobsearch.private_resume ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobsearch.private_resume FORCE ROW LEVEL SECURITY;
ALTER TABLE jobsearch.private_applications ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobsearch.private_applications FORCE ROW LEVEL SECURITY;
CREATE POLICY own_intake ON jobsearch.private_intake USING (user_id=nullif(current_setting('jobsearch.user_id',true),'')::bigint) WITH CHECK (user_id=nullif(current_setting('jobsearch.user_id',true),'')::bigint);
CREATE POLICY own_resume ON jobsearch.private_resume USING (user_id=nullif(current_setting('jobsearch.user_id',true),'')::bigint) WITH CHECK (user_id=nullif(current_setting('jobsearch.user_id',true),'')::bigint);
CREATE POLICY own_applications ON jobsearch.private_applications USING (user_id=nullif(current_setting('jobsearch.user_id',true),'')::bigint) WITH CHECK (user_id=nullif(current_setting('jobsearch.user_id',true),'')::bigint);
GRANT SELECT,INSERT,UPDATE,DELETE ON jobsearch.private_intake,jobsearch.private_resume,jobsearch.private_applications TO jobsearch_app;
INSERT INTO jobsearch.schema_versions(version) VALUES(6);
