
CREATE OR REPLACE FUNCTION jobsearch.posting_identity(url text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT split_part(split_part(url,'#',1),'?',1) || coalesce(
  (SELECT '?' || string_agg(part,'&' ORDER BY part) FROM unnest(string_to_array(split_part(split_part(url,'#',1),'?',2),'&')) part
   WHERE part<>'' AND lower(split_part(part,'=',1)) NOT LIKE 'utm_%' AND lower(split_part(part,'=',1)) NOT IN ('gh_src','source','ref','referrer')), '')
$$;
CREATE TABLE IF NOT EXISTS jobsearch.job_dismissals (
 user_id bigint NOT NULL REFERENCES jobsearch.users(id) ON DELETE CASCADE,
 identity text NOT NULL,
 job_id uuid NOT NULL REFERENCES jobsearch.jobs(id) ON DELETE CASCADE,
 reason text NOT NULL CHECK(reason IN ('old_posting','already_applied_elsewhere','not_interested','no_longer_available')),
 updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(user_id,identity)
);
CREATE INDEX IF NOT EXISTS dismissal_job_owner ON jobsearch.job_dismissals(user_id,job_id);
ALTER TABLE jobsearch.job_dismissals ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobsearch.job_dismissals FORCE ROW LEVEL SECURITY;
CREATE POLICY own_dismissals ON jobsearch.job_dismissals USING(user_id=nullif(current_setting('jobsearch.user_id',true),'')::bigint) WITH CHECK(user_id=nullif(current_setting('jobsearch.user_id',true),'')::bigint);
GRANT SELECT,INSERT,UPDATE,DELETE ON jobsearch.job_dismissals TO jobsearch_app;
INSERT INTO jobsearch.schema_versions(version) VALUES(7) ON CONFLICT DO NOTHING;
