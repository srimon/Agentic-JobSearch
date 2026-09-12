ALTER TABLE jobsearch.job_archives ADD COLUMN feedback_reason text CHECK(feedback_reason IN ('wrong_function','wrong_seniority','wrong_workplace'));
CREATE TABLE jobsearch.learning_settings (
 user_id bigint PRIMARY KEY REFERENCES jobsearch.users(id) ON DELETE CASCADE,
 enabled boolean NOT NULL DEFAULT true, since timestamptz, pinned_version bigint
);
CREATE TABLE jobsearch.learning_versions (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 user_id bigint NOT NULL REFERENCES jobsearch.users(id) ON DELETE CASCADE,
 fingerprint text NOT NULL, model jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(user_id,fingerprint)
);
ALTER TABLE jobsearch.learning_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobsearch.learning_settings FORCE ROW LEVEL SECURITY;
CREATE POLICY own_learning_settings ON jobsearch.learning_settings USING(user_id=nullif(current_setting('jobsearch.user_id',true),'')::bigint) WITH CHECK(user_id=nullif(current_setting('jobsearch.user_id',true),'')::bigint);
ALTER TABLE jobsearch.learning_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobsearch.learning_versions FORCE ROW LEVEL SECURITY;
CREATE POLICY own_learning_versions ON jobsearch.learning_versions USING(user_id=nullif(current_setting('jobsearch.user_id',true),'')::bigint) WITH CHECK(user_id=nullif(current_setting('jobsearch.user_id',true),'')::bigint);
GRANT SELECT,INSERT,UPDATE ON jobsearch.learning_settings TO jobsearch_app;
GRANT SELECT,INSERT ON jobsearch.learning_versions TO jobsearch_app;
GRANT USAGE,SELECT ON SEQUENCE jobsearch.learning_versions_id_seq TO jobsearch_app;
INSERT INTO jobsearch.schema_versions(version) VALUES(11);
