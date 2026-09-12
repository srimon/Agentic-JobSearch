
ALTER TABLE jobsearch.job_dismissals DROP CONSTRAINT job_dismissals_reason_check;
ALTER TABLE jobsearch.job_dismissals ADD CONSTRAINT job_dismissals_reason_check CHECK(reason IN ('old_posting','already_applied_elsewhere','not_interested','no_longer_available','not_relevant','dismissed'));
INSERT INTO jobsearch.schema_versions(version) VALUES(8) ON CONFLICT DO NOTHING;
