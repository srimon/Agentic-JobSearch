ALTER TABLE jobsearch.sources DROP CONSTRAINT IF EXISTS sources_provider_check;
ALTER TABLE jobsearch.sources ADD CONSTRAINT sources_provider_check CHECK(provider IN ('ashby','greenhouse','lever','dice'));
INSERT INTO jobsearch.sources(company,provider,board,enabled) VALUES('Dice US leadership search','dice','us-leadership',true) ON CONFLICT(provider,board) DO NOTHING;
INSERT INTO jobsearch.schema_versions(version) VALUES(4) ON CONFLICT DO NOTHING;
