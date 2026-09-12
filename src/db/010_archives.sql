CREATE TABLE jobsearch.job_archives (
 user_id bigint NOT NULL REFERENCES jobsearch.users(id) ON DELETE CASCADE,
 identity text NOT NULL,
 job_id uuid NOT NULL REFERENCES jobsearch.jobs(id) ON DELETE CASCADE,
 final_status text NOT NULL,
 archived_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(user_id,identity)
);
INSERT INTO jobsearch.job_archives(user_id,identity,job_id,final_status)
 SELECT DISTINCT ON(e.user_id,jobsearch.posting_identity(j.url)) e.user_id,jobsearch.posting_identity(j.url),j.id,
 coalesce(d.reason,s.stage)
 FROM jobsearch.emailed_jobs e JOIN jobsearch.jobs j ON j.id=e.job_id
 LEFT JOIN jobsearch.saved_jobs s ON s.user_id=e.user_id AND s.job_id=j.id
 LEFT JOIN jobsearch.job_dismissals d ON d.user_id=e.user_id AND d.identity=jobsearch.posting_identity(j.url)
 WHERE e.emailed_at IS NOT NULL AND (d.reason IS NOT NULL OR s.stage IN ('applied','interviewing','offer','closed'))
 ORDER BY e.user_id,jobsearch.posting_identity(j.url),e.emailed_at DESC;
ALTER TABLE jobsearch.job_archives ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobsearch.job_archives FORCE ROW LEVEL SECURITY;
CREATE POLICY own_archives ON jobsearch.job_archives USING(user_id=nullif(current_setting('jobsearch.user_id',true),'')::bigint) WITH CHECK(user_id=nullif(current_setting('jobsearch.user_id',true),'')::bigint);
GRANT SELECT,INSERT ON jobsearch.job_archives TO jobsearch_app;
INSERT INTO jobsearch.schema_versions(version) VALUES(10);
