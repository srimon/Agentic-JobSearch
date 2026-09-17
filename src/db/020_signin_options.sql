-- The owner's decisions of 17 September 2026 (evening) on the account creation options (the hub's
-- docs/plans/account-creation-options.md): a fourth consent purpose, news; approving a sign-in from a
-- phone that is already signed in (QR flow 2); the phone's own rows in the sign-up record. Additive.
--
-- No SMS and no phone numbers: account_context.phone_e164 and phone_verified_at stay in place, unused
-- (nothing writes them; dropping a column is not additive), so the schema records the decision.
ALTER TABLE jobsearch.user_consent ADD COLUMN IF NOT EXISTS news boolean NOT NULL DEFAULT false;
ALTER TABLE jobsearch.consent_events ADD COLUMN IF NOT EXISTS news boolean NOT NULL DEFAULT false;
-- A phone that approves a sign-in leaves its own context row, source 'approve'.
ALTER TABLE jobsearch.account_context DROP CONSTRAINT IF EXISTS account_context_source_check;
ALTER TABLE jobsearch.account_context ADD CONSTRAINT account_context_source_check CHECK(source IN ('desktop','qr-phone','signin','approve'));
-- mfa_scan_codes: the code a two-step page draws as a QR for the challenge in its cookie. A phone that
-- is signed in as the same account opens the code's address, sees what device is asking (device: the
-- desktop's device class, browser, system, city and country, never its address) and approves; the
-- desktop's poll then completes the sign-in. Stored as a digest, 128 bits, single use, and gone with
-- its challenge (the sign-in housekeeping deletes expired challenges).
CREATE TABLE IF NOT EXISTS jobsearch.mfa_scan_codes (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 code_hash text NOT NULL UNIQUE,
 challenge_hash text NOT NULL REFERENCES jobsearch.mfa_challenges(token_hash) ON DELETE CASCADE,
 user_id bigint NOT NULL REFERENCES jobsearch.users(id) ON DELETE CASCADE,
 device jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
 approved_at timestamptz, approver_context_id bigint REFERENCES jobsearch.account_context(id) ON DELETE SET NULL,
 consumed_at timestamptz
);
CREATE INDEX IF NOT EXISTS mfa_scan_codes_challenge ON jobsearch.mfa_scan_codes(challenge_hash, id);
GRANT SELECT,INSERT,UPDATE,DELETE ON jobsearch.mfa_scan_codes TO jobsearch_app;
GRANT USAGE,SELECT ON SEQUENCE jobsearch.mfa_scan_codes_id_seq TO jobsearch_app;
INSERT INTO jobsearch.schema_versions(version) VALUES(20) ON CONFLICT DO NOTHING;
