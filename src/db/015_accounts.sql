-- Self-service accounts (ADR 0004): verified email addresses, single-use tokens and the outbound mail queue.
ALTER TABLE jobsearch.users ADD COLUMN IF NOT EXISTS email text;
ALTER TABLE jobsearch.users ADD COLUMN IF NOT EXISTS email_verified_at timestamptz;
ALTER TABLE jobsearch.users ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE jobsearch.users ADD COLUMN IF NOT EXISTS last_login_at timestamptz;
CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower ON jobsearch.users(lower(email)) WHERE email IS NOT NULL;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='users_roles_check' AND conrelid='jobsearch.users'::regclass) THEN
  ALTER TABLE jobsearch.users ADD CONSTRAINT users_roles_check CHECK(roles <@ ARRAY['viewer','member','operator','administrator']::text[]);
 END IF;
END $$;
CREATE TABLE IF NOT EXISTS jobsearch.auth_tokens (
 token_hash text PRIMARY KEY, user_id bigint NOT NULL REFERENCES jobsearch.users(id) ON DELETE CASCADE,
 purpose text NOT NULL CHECK(purpose IN ('verify','reset')), expires_at timestamptz NOT NULL,
 used_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS auth_tokens_user ON jobsearch.auth_tokens(user_id,purpose);
CREATE TABLE IF NOT EXISTS jobsearch.outbound_mail (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, purpose text NOT NULL,
 to_address text NOT NULL, subject text NOT NULL, text_body text NOT NULL, html_body text,
 status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','sent','failed')),
 attempts integer NOT NULL DEFAULT 0, last_error text, provider_id text,
 created_at timestamptz NOT NULL DEFAULT now(), sent_at timestamptz
);
CREATE INDEX IF NOT EXISTS outbound_mail_queued ON jobsearch.outbound_mail(id) WHERE status='queued';
GRANT SELECT,INSERT,UPDATE,DELETE ON jobsearch.auth_tokens TO jobsearch_app;
GRANT SELECT,INSERT,UPDATE ON jobsearch.outbound_mail TO jobsearch_app;
GRANT USAGE,SELECT ON SEQUENCE jobsearch.outbound_mail_id_seq TO jobsearch_app;
INSERT INTO jobsearch.schema_versions(version) VALUES(15) ON CONFLICT DO NOTHING;
