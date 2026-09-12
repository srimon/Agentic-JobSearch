ALTER TABLE jobsearch.sources DROP CONSTRAINT IF EXISTS sources_provider_check;
ALTER TABLE jobsearch.sources ADD CONSTRAINT sources_provider_check CHECK(provider IN ('ashby','greenhouse','lever','dice','jobicy','remotive'));
INSERT INTO jobsearch.sources(company,provider,board,enabled) VALUES('Jobicy US remote jobs','jobicy','us-remote',true),('Remotive remote jobs','remotive','remote',true) ON CONFLICT(provider,board) DO NOTHING;
INSERT INTO jobsearch.schema_versions(version) VALUES(5) ON CONFLICT DO NOTHING;
