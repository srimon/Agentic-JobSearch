-- Account creation options (the hub's docs/plans/account-creation-options.md, 17 Sep 2026): the
-- sign-up context record, the phone-scan check of a sign-up, consent choices, and the e-mail
-- one-time code as a second sign-in step for accounts without an authenticator app.
--
-- signup_attempts: one row per sign-up form opened with the phone-scan check on. The desktop
-- holds one secret (it polls and submits with it) and the QR code holds another; both are stored
-- as SHA-256 digests like sessions and tokens, live for settings.signup_scan_seconds, and are
-- spent once. The desktop's address is kept to say whether the phone was on the same network.
CREATE TABLE IF NOT EXISTS jobsearch.signup_attempts (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 desktop_hash text NOT NULL UNIQUE,
 scan_hash text NOT NULL UNIQUE,
 client_hash text NOT NULL,
 ip inet,
 created_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL,
 scanned_at timestamptz,
 consumed_at timestamptz,
 user_id bigint REFERENCES jobsearch.users(id) ON DELETE SET NULL,
 consent jsonb
);
CREATE INDEX IF NOT EXISTS signup_attempts_expiry ON jobsearch.signup_attempts(expires_at);
-- account_context: what was known about the visitor when the account was made (source desktop),
-- when a phone confirmed the sign-up by scanning its code (qr-phone, keyed to the account once
-- the sign-up completes) and, kept for settings.context_signin_retention_days, at each sign-in
-- (signin). Personal data: keyed to the account and deleted with it, read by administrators
-- only, never written to logs or audit records. The address is stored as sent on purpose, for
-- abuse investigation; the edge statistics keep only their hashed form.
CREATE TABLE IF NOT EXISTS jobsearch.account_context (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 user_id bigint REFERENCES jobsearch.users(id) ON DELETE CASCADE,
 attempt_id bigint REFERENCES jobsearch.signup_attempts(id) ON DELETE SET NULL,
 source text NOT NULL CHECK(source IN ('desktop','qr-phone','signin')),
 recorded_at timestamptz NOT NULL DEFAULT now(),
 ip inet, country text, continent text, region text, region_code text, city text, postal_code text, timezone text,
 latitude numeric(9,6), longitude numeric(9,6),
 user_agent text, device_class text NOT NULL DEFAULT 'unknown' CHECK(device_class IN ('phone','tablet','desktop','bot','unknown')),
 os text, browser text, accept_language text, referrer text, address text,
 screen_width integer, screen_height integer, pixel_ratio numeric(6,3), touch_points integer,
 language text, client_timezone text, challenge_cookie boolean,
 scan_seconds numeric(8,2), same_network boolean,
 phone_e164 text, phone_verified_at timestamptz
);
CREATE INDEX IF NOT EXISTS account_context_user ON jobsearch.account_context(user_id, recorded_at);
CREATE INDEX IF NOT EXISTS account_context_attempt ON jobsearch.account_context(attempt_id) WHERE attempt_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS account_context_recorded ON jobsearch.account_context(source, recorded_at);
-- The account was confirmed by a phone scan during sign-up (a stronger person signal than mail alone).
ALTER TABLE jobsearch.users ADD COLUMN IF NOT EXISTS scan_verified_at timestamptz;
-- Consent for use of the data beyond running the service: the current choice per purpose, and
-- every change with the notice that was shown (version and digest), the regime the visitor's
-- location put them under, the choice, when and from where. A withdrawal is a new event and a
-- changed current row, so exports keyed to user_consent stop at once.
CREATE TABLE IF NOT EXISTS jobsearch.user_consent (
 user_id bigint PRIMARY KEY REFERENCES jobsearch.users(id) ON DELETE CASCADE,
 analytics boolean NOT NULL DEFAULT false, partners boolean NOT NULL DEFAULT false, advertising boolean NOT NULL DEFAULT false,
 notice_version text NOT NULL, regime text NOT NULL CHECK(regime IN ('eu','uk','california','other')),
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS jobsearch.consent_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 user_id bigint NOT NULL REFERENCES jobsearch.users(id) ON DELETE CASCADE,
 recorded_at timestamptz NOT NULL DEFAULT now(),
 source text NOT NULL CHECK(source IN ('signup','qr-phone','account')),
 notice_version text NOT NULL, notice_hash text NOT NULL,
 regime text NOT NULL CHECK(regime IN ('eu','uk','california','other')),
 analytics boolean NOT NULL, partners boolean NOT NULL, advertising boolean NOT NULL,
 ip inet, country text
);
CREATE INDEX IF NOT EXISTS consent_events_user ON jobsearch.consent_events(user_id, recorded_at);
-- The e-mail one-time code as a second step: a challenge row says which method it waits for.
-- An e-mail challenge carries the digest of its six-digit code and how often it was re-sent.
ALTER TABLE jobsearch.mfa_challenges ADD COLUMN IF NOT EXISTS method text NOT NULL DEFAULT 'totp';
ALTER TABLE jobsearch.mfa_challenges ADD COLUMN IF NOT EXISTS code_hash text;
ALTER TABLE jobsearch.mfa_challenges ADD COLUMN IF NOT EXISTS resends integer NOT NULL DEFAULT 0;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='mfa_challenges_method_check' AND conrelid='jobsearch.mfa_challenges'::regclass) THEN
  ALTER TABLE jobsearch.mfa_challenges ADD CONSTRAINT mfa_challenges_method_check CHECK(method IN ('totp','email'));
 END IF;
END $$;
GRANT SELECT,INSERT,UPDATE,DELETE ON jobsearch.signup_attempts,jobsearch.account_context,jobsearch.user_consent,jobsearch.consent_events TO jobsearch_app;
GRANT USAGE,SELECT ON SEQUENCE jobsearch.signup_attempts_id_seq,jobsearch.account_context_id_seq,jobsearch.consent_events_id_seq TO jobsearch_app;
INSERT INTO jobsearch.schema_versions(version) VALUES(19) ON CONFLICT DO NOTHING;
