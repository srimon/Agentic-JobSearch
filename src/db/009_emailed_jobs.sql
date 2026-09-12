
CREATE TABLE jobsearch.emailed_jobs (
 user_id bigint NOT NULL REFERENCES jobsearch.users(id) ON DELETE CASCADE,
 report_hash text NOT NULL CHECK(length(report_hash)=64),
 job_id uuid NOT NULL REFERENCES jobsearch.jobs(id) ON DELETE CASCADE,
 prepared_at timestamptz NOT NULL DEFAULT now(),
 emailed_at timestamptz,
 PRIMARY KEY(user_id,report_hash,job_id)
);
CREATE INDEX emailed_jobs_owner_job ON jobsearch.emailed_jobs(user_id,job_id,emailed_at);
ALTER TABLE jobsearch.emailed_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobsearch.emailed_jobs FORCE ROW LEVEL SECURITY;
CREATE POLICY own_emailed_jobs ON jobsearch.emailed_jobs USING(user_id=nullif(current_setting('jobsearch.user_id',true),'')::bigint) WITH CHECK(user_id=nullif(current_setting('jobsearch.user_id',true),'')::bigint);
GRANT SELECT,INSERT,UPDATE ON jobsearch.emailed_jobs TO jobsearch_app;
INSERT INTO jobsearch.schema_versions(version) VALUES(9);
