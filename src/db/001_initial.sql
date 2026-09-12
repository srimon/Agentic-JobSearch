CREATE SCHEMA IF NOT EXISTS jobsearch;
CREATE TABLE IF NOT EXISTS jobsearch.schema_versions(version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS jobsearch.users (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 issuer text NOT NULL, subject text NOT NULL, display_name text NOT NULL DEFAULT '',
 roles text[] NOT NULL DEFAULT ARRAY['viewer'], active boolean NOT NULL DEFAULT true,
 UNIQUE(issuer,subject)
);
CREATE TABLE IF NOT EXISTS jobsearch.sessions (
 token_hash text PRIMARY KEY, user_id bigint NOT NULL REFERENCES jobsearch.users(id),
 expires_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS jobsearch.sources (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, company text NOT NULL,
 provider text NOT NULL CHECK(provider IN ('ashby','greenhouse','lever')), board text NOT NULL,
 enabled boolean NOT NULL DEFAULT false, last_success_at timestamptz, last_error text,
 UNIQUE(provider,board)
);
CREATE TABLE IF NOT EXISTS jobsearch.runs (
 id uuid PRIMARY KEY, source_id bigint REFERENCES jobsearch.sources(id),
 status text NOT NULL CHECK(status IN ('queued','running','completed','failed')),
 requested_by text NOT NULL, started_at timestamptz, finished_at timestamptz,
 fetched integer NOT NULL DEFAULT 0, matched integer NOT NULL DEFAULT 0, error text,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_source_run ON jobsearch.runs(source_id) WHERE status IN ('queued','running');
CREATE TABLE IF NOT EXISTS jobsearch.jobs (
 id uuid PRIMARY KEY, source_id bigint NOT NULL REFERENCES jobsearch.sources(id), source_job_id text NOT NULL,
 company text NOT NULL, title text NOT NULL, location text NOT NULL, work_mode text NOT NULL,
 country_status text NOT NULL, level text NOT NULL, match_status text NOT NULL, reason text NOT NULL,
 description text NOT NULL, url text NOT NULL, posted_at timestamptz,
 first_seen_at timestamptz NOT NULL DEFAULT now(), last_seen_at timestamptz NOT NULL DEFAULT now(),
 availability text NOT NULL DEFAULT 'observed_open', content_hash text NOT NULL,
 evidence jsonb NOT NULL DEFAULT '{}', UNIQUE(source_id,source_job_id)
);
CREATE INDEX IF NOT EXISTS jobs_filter ON jobsearch.jobs(match_status,country_status,posted_at DESC);
CREATE TABLE IF NOT EXISTS jobsearch.observations (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, job_id uuid NOT NULL REFERENCES jobsearch.jobs(id),
 run_id uuid NOT NULL REFERENCES jobsearch.runs(id), content_hash text NOT NULL,
 evidence jsonb NOT NULL, observed_at timestamptz NOT NULL DEFAULT now(), UNIQUE(job_id,run_id)
);
CREATE TABLE IF NOT EXISTS jobsearch.saved_jobs (
 user_id bigint NOT NULL REFERENCES jobsearch.users(id), job_id uuid NOT NULL REFERENCES jobsearch.jobs(id),
 stage text NOT NULL DEFAULT 'saved' CHECK(stage IN ('saved','applied','interviewing','offer','closed')),
 saved_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(user_id,job_id)
);
CREATE TABLE IF NOT EXISTS jobsearch.audit_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, at timestamptz NOT NULL DEFAULT now(),
 actor text NOT NULL, action text NOT NULL, resource text NOT NULL DEFAULT '', outcome text NOT NULL,
 details jsonb NOT NULL DEFAULT '{}'
);
INSERT INTO jobsearch.schema_versions(version) VALUES(1) ON CONFLICT DO NOTHING;
