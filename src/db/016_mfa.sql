-- Optional two-step sign-in (TOTP, RFC 6238): encrypted authenticator secrets, single-use recovery codes and
-- short-lived login challenges between the password step and the code step.
CREATE TABLE IF NOT EXISTS jobsearch.user_mfa (
 user_id bigint PRIMARY KEY REFERENCES jobsearch.users(id) ON DELETE CASCADE,
 secret_enc bytea NOT NULL, enabled_at timestamptz, last_used_step bigint,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS jobsearch.mfa_recovery_codes (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 user_id bigint NOT NULL REFERENCES jobsearch.users(id) ON DELETE CASCADE,
 code_hash text NOT NULL, used_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(user_id,code_hash)
);
CREATE TABLE IF NOT EXISTS jobsearch.mfa_challenges (
 token_hash text PRIMARY KEY, user_id bigint NOT NULL REFERENCES jobsearch.users(id) ON DELETE CASCADE,
 expires_at timestamptz NOT NULL, attempts integer NOT NULL DEFAULT 0 CHECK(attempts >= 0),
 consumed_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mfa_challenges_user ON jobsearch.mfa_challenges(user_id);
CREATE INDEX IF NOT EXISTS mfa_challenges_expiry ON jobsearch.mfa_challenges(expires_at);
GRANT SELECT,INSERT,UPDATE,DELETE ON jobsearch.user_mfa,jobsearch.mfa_recovery_codes,jobsearch.mfa_challenges TO jobsearch_app;
GRANT USAGE,SELECT ON SEQUENCE jobsearch.mfa_recovery_codes_id_seq TO jobsearch_app;
INSERT INTO jobsearch.schema_versions(version) VALUES(16) ON CONFLICT DO NOTHING;
