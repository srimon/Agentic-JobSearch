# Configuration

All settings are read by `src/settings.py` from the environment with the `JOBSEARCH_` prefix (or from `.env` / `/run/secrets/app_env`). Lists are comma-separated; link maps are JSON objects. Settings introduced with self-service accounts (ADR 0004) are marked new.

| Variable | Default | Purpose |
|---|---|---|
| JOBSEARCH_DATABASE_URL | (empty) | PostgreSQL DSN; the API and mailer use the scoped `jobsearch_app` role. |
| JOBSEARCH_DATA_MANAGEMENT_ENABLED | false | Exposes the production data-management endpoints. |
| JOBSEARCH_MAINTENANCE_MODE | false | Rejects state-changing requests except sign-in/out with 503. |
| JOBSEARCH_ORIGIN | http://localhost:3105 | Local browser origin of the front end. |
| JOBSEARCH_PUBLIC_ORIGIN (new) | = origin | Browser-facing address used in emailed links and in the sign-in returns other products send; may carry a path. Production `https://bagala.ai/jobsearch` (the short path on the shared host; `https://jobs.bagala.ai` still serves the same deployment). |
| JOBSEARCH_ALLOWED_ORIGINS (new) | origin plus public_origin | Origins accepted by the CSRF check for POST/PUT/PATCH/DELETE (exact match on the `Origin` header). |
| JOBSEARCH_HUB_ORIGINS (new) | http://localhost:3180 | Origins allowed to read `/api/workflow` with credentials (CORS special case). |
| JOBSEARCH_LIBRARY_ORIGINS (new) | http://localhost:3001,http://localhost:3011,http://localhost:8000,http://localhost:8010 | Origins the library gateway may forward for state-changing requests to `/api/hub/library-authorize`. |
| JOBSEARCH_READER_DAILY_QUESTION_LIMIT | 50 | Library Reader questions (`POST /api?op=ask`) a non-administrator may ask per UTC day, enforced by `/api/hub/library-authorize`; `0` = unlimited. Over the limit the Library gateway answers a JSON 429 with `Retry-After` until midnight UTC. |
| JOBSEARCH_HUB_LINKS_LOCAL (new) | {"hub":"http://localhost:3180/","library":"http://localhost:3001/reader","prep":"http://localhost:3188/"} | Links returned by `/api/session` when the request host is not on the cookie domain. |
| JOBSEARCH_HUB_LINKS_PUBLIC (new) | {"hub":"https://hub.bagala.ai/","library":"https://library.bagala.ai/reader","prep":"https://bagala.ai/jobprep/"} | Links returned by `/api/session` when the request host is the cookie domain or a subdomain of it. |
| JOBSEARCH_COOKIE_DOMAIN (new) | (empty = host-only) | Session cookie `Domain`, applied only to requests whose host matches it; e.g. `bagala.ai`. |
| JOBSEARCH_COOKIE_SAMESITE (new) | lax | `lax`, `strict` or `none` (`none` needs Secure). |
| JOBSEARCH_SECURE_COOKIES | true when public_origin is https, else false | Allows the `Secure` flag; it is set per request only when the request arrived over HTTPS (scheme or `X-Forwarded-Proto: https`). |
| JOBSEARCH_SESSION_HOURS | 8 | Session lifetime. |
| JOBSEARCH_IDLE_MINUTES (new) | 5 | A signed-in account that is not an administrator is signed out after this many minutes without an authenticated request, in every product that authenticates here; the session row is deleted and the request answered 401. Administrators are exempt. `0` switches it off. |
| JOBSEARCH_SIGNUP_ENABLED (new) | false | Enables `POST /api/auth/signup`; otherwise it answers 404. |
| JOBSEARCH_SIGNUP_DEFAULT_ROLES (new) | viewer | Roles granted to self-registered accounts (subset of viewer, member, operator, administrator). |
| JOBSEARCH_MAIL_TRANSPORT (new) | log | `log` prints a redacted event per message; `resend` posts to https://api.resend.com/emails. |
| JOBSEARCH_MAIL_FROM (new) | Bagala <no-reply@bagala.ai> | Sender for account mail. |
| JOBSEARCH_RESEND_API_KEY_FILE (new) | /run/secrets/resend/api.key | File holding the Resend key, read at send time; never logged. |
| JOBSEARCH_MAILER_HEARTBEAT (new) | /tmp/jobsearch-mailer-heartbeat | File touched by `scripts/mailer.py` after every successful pass, for liveness probes. |
| JOBSEARCH_REPORT_RECIPIENT (new) | sean.chopparapu@gmail.com | Sender and sole recipient of the Gmail application report. |
| JOBSEARCH_OWNER_USERNAME (new) | admin | Local username that owns the daily workflow and the report. |
| JOBSEARCH_SCHEDULE_HOURS | 24 | Minimum hours between scheduled collections of a source. |
| JOBSEARCH_SCHEDULE_HOUR | 8 | Local hour of the daily workflow (0-23). |
| JOBSEARCH_SCHEDULE_TIMEZONE | America/Los_Angeles | Time zone of the daily workflow. |
| JOBSEARCH_WORKER_LEASE_SECONDS | 120 | Collection lease duration (10-600). |
| JOBSEARCH_WORKER_HEARTBEAT_SECONDS | 20 | Lease heartbeat interval; at most a third of the lease. |
| JOBSEARCH_WORKER_MAX_RUN_SECONDS | 900 | Hard limit for one collection run (30-7200, above the lease). |
| JOBSEARCH_WORKER_SHUTDOWN_SECONDS | 60 | Grace period after SIGTERM before the worker exits (1-300). |
| JOBSEARCH_WORKER_MAX_ATTEMPTS | 3 | Attempts per collection run (1-10). |
| JOBSEARCH_MAX_RESPONSE_BYTES | 20000000 | Upper bound for fetched source responses. |

Related variables read directly from the environment rather than settings: `JOBSEARCH_TELEMETRY`, `JOBSEARCH_OTLP_LOGS`, `JOBSEARCH_ENVIRONMENT`, `JOBSEARCH_INTAKE_KEY_FILE`, `JOBSEARCH_FETCH_PROXY`, the `JOBSEARCH_REPORT_*` transport variables in [portable reporting](playbooks/portable-reporting.md), and `JOBSEARCH_AUTH_TEST` (disposable test database guard).

Production values for bagala.ai: `JOBSEARCH_PUBLIC_ORIGIN=https://bagala.ai/jobsearch`, `JOBSEARCH_ALLOWED_ORIGINS=http://localhost:3105,https://jobs.bagala.ai,https://bagala.ai`, `JOBSEARCH_IDLE_MINUTES=5`, `JOBSEARCH_COOKIE_DOMAIN=bagala.ai`, `JOBSEARCH_HUB_ORIGINS=http://localhost:3180,https://hub.bagala.ai,https://bagala.ai`, `JOBSEARCH_LIBRARY_ORIGINS=https://library.bagala.ai,...`, `JOBSEARCH_SIGNUP_ENABLED=true`, `JOBSEARCH_MAIL_TRANSPORT=resend` with the key mounted at the configured path, and `HTTPS_PROXY` for the mailer pod's egress.
