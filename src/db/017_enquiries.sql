-- Enquiries sent from the "Email Admin" dialog in every product footer and public page (POST /api/enquiries).
-- client_hash is a SHA-256 digest of the forwarded client address; the address itself is never stored.
CREATE TABLE IF NOT EXISTS jobsearch.enquiries (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 name text NOT NULL CHECK(char_length(name) BETWEEN 1 AND 120),
 email text NOT NULL CHECK(char_length(email) BETWEEN 6 AND 254),
 message text NOT NULL CHECK(char_length(message) BETWEEN 10 AND 2000),
 page text CHECK(page IS NULL OR char_length(page) <= 200),
 client_hash text,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS enquiries_created ON jobsearch.enquiries(created_at);
GRANT SELECT,INSERT ON jobsearch.enquiries TO jobsearch_app;
GRANT USAGE,SELECT ON SEQUENCE jobsearch.enquiries_id_seq TO jobsearch_app;
INSERT INTO jobsearch.schema_versions(version) VALUES(17) ON CONFLICT DO NOTHING;
