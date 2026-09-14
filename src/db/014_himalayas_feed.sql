ALTER TABLE jobsearch.sources DROP CONSTRAINT sources_provider_check;
ALTER TABLE jobsearch.sources ADD CONSTRAINT sources_provider_check CHECK(provider IN ('ashby','greenhouse','lever','dice','jobicy','remotive','himalayas'));
-- Enable only after the collector and exact-host egress release is verified.
INSERT INTO jobsearch.sources(company,provider,board,enabled) VALUES('Himalayas US leadership jobs','himalayas','us-leadership',false) ON CONFLICT(provider,board) DO NOTHING;
INSERT INTO jobsearch.schema_versions(version) VALUES(14) ON CONFLICT DO NOTHING;
