-- API keys (stage 2 of the hub's docs/plans/api-gateway-and-mcp.md, 17 Sep 2026): a program's way in.
--
-- A key is "hub_<id>_<secret>": the id is the public prefix (12 hex characters, the primary key here, what
-- the gateway keys its rate limit on before the secret is checked), the secret is 32 random bytes shown once
-- at creation and stored as its SHA-256 digest, like a session token. A key belongs to one account and
-- carries that account's roles at the time of the call; it never has roles of its own. Several named keys
-- per account. Revocation keeps the row (revoked_at) for the audit trail; deleting the account deletes its
-- keys. products is the subset of the three products the key may reach; daily_quota is calls per UTC day
-- (0 = unlimited), counted in api_key_days: one row per key and day with the calls made and how many of
-- them were refused over the quota, which is the per-day audit of key use. Additive.
CREATE TABLE IF NOT EXISTS jobsearch.api_keys (
 id text PRIMARY KEY CHECK(id ~ '^[0-9a-f]{12}$'),
 user_id bigint NOT NULL REFERENCES jobsearch.users(id) ON DELETE CASCADE,
 name text NOT NULL CHECK(length(name) BETWEEN 1 AND 60),
 secret_hash text NOT NULL UNIQUE,
 products text[] NOT NULL DEFAULT ARRAY['jobsearch','library','prep']::text[]
  CHECK(products <@ ARRAY['jobsearch','library','prep']::text[] AND cardinality(products) >= 1),
 daily_quota integer NOT NULL CHECK(daily_quota >= 0),
 created_at timestamptz NOT NULL DEFAULT now(),
 last_used_at timestamptz,
 revoked_at timestamptz,
 UNIQUE(user_id, name)
);
CREATE INDEX IF NOT EXISTS api_keys_user ON jobsearch.api_keys(user_id, created_at);
CREATE TABLE IF NOT EXISTS jobsearch.api_key_days (
 key_id text NOT NULL REFERENCES jobsearch.api_keys(id) ON DELETE CASCADE,
 day date NOT NULL,
 calls integer NOT NULL DEFAULT 0,
 refused integer NOT NULL DEFAULT 0,
 PRIMARY KEY(key_id, day)
);
GRANT SELECT,INSERT,UPDATE ON jobsearch.api_keys,jobsearch.api_key_days TO jobsearch_app;
INSERT INTO jobsearch.schema_versions(version) VALUES(21) ON CONFLICT DO NOTHING;
