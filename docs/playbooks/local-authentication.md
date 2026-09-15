# Local authentication operations

Run from `/home/srimonadi/Enterprise-AI-Hub/apps/jobsearch`. The application must be running. `./scripts/account.sh` routes to the active runtime: with `.compose-retired` present it executes `/home/srimonadi/Enterprise-AI-Hub/scripts/jobsearch_account.py`, which runs `python -m scripts.accounts` inside the production API pod (`jbs-production`, interactive terminal required); otherwise it uses the Compose container.

Create the first administrator (choose your own username):

```bash
./scripts/account.sh create admin --name "Jobsearch Administrator" --roles administrator member operator
```

The command prompts twice for a 15-128 character password without displaying it. No default password or browser bootstrap endpoint exists. Do not put passwords in command arguments or chat.

Open http://localhost:3105 (or https://jobs.bagala.ai) and sign in with that account.

```bash
./scripts/account.sh create anotheruser --roles member
./scripts/account.sh reset admin
./scripts/account.sh disable anotheruser
./scripts/account.sh enable anotheruser
./scripts/account.sh revoke admin
./scripts/account.sh roles anotheruser --roles member operator
./scripts/account.sh email anotheruser person@example.com
./scripts/account.sh verify anotheruser
```

Reset, disable, enable and revoke invalidate all existing sessions for the user; roles, email and verify keep them (roles are read from the database on every request). A reset does not re-enable a disabled account. Account creation rejects duplicates. `email` stores the address unverified and queues a verification mail; until the person confirms it (or you run `verify`) sign-in answers "Verify your email address before signing in." Audit records contain actions and account IDs, never password values, addresses or tokens. Trusted local OS/Docker access authorizes the console; anyone with Docker or kubectl access is already a host administrator equivalent.

## Self-service accounts (ADR 0004)

With `JOBSEARCH_SIGNUP_ENABLED=true` the front end offers sign-up, "resend the link", "forgot password", a profile page (display name, email, password) and a session list. Flow:

1. `POST /api/auth/signup` creates an unverified account with the `JOBSEARCH_SIGNUP_DEFAULT_ROLES` roles and queues a verification mail (link `{public_origin}/?verify=<token>`, 24 hours, single use).
2. `POST /api/auth/verify {token}` confirms the address; `POST /api/auth/resend {email}` queues a fresh link for an unverified account.
3. `POST /api/auth/reset-request {email}` queues `{public_origin}/?reset=<token>` (1 hour); `POST /api/auth/reset {token,password}` sets the password, marks the address verified and signs out every session.
4. Signed in: `GET/PATCH /api/auth/profile`, `POST /api/auth/password {current,new}` (signs out the other sessions), `GET /api/auth/sessions`, `POST /api/auth/sessions/revoke-all` (keeps the current session).

All anonymous responses are identical whether or not the account exists; check `jobsearch.audit_events` (actions `account.*`, outcomes `allowed`, `duplicate`, `ignored`, `queued`, `denied`, `throttled`) when someone reports a missing mail. Rate limits share `jobsearch.login_limits`: sign-up 30 per 15 minutes globally and 5 per address, mail requests 60 and 3, password changes 10 per account; a throttled request answers 429 with `Retry-After: 900`. Promote a self-registered account with `roles`.

## Mail delivery

Account mail is queued in `jobsearch.outbound_mail` and sent by one replica of `JBS/bin/python -m scripts.mailer` (`--once` drains the queue and exits, for jobs and tests). `JOBSEARCH_MAIL_TRANSPORT=log` only prints `{"event":"mail.sent","purpose":..,"to_domain":..}`; `resend` posts to the Resend API with the key read from `JOBSEARCH_RESEND_API_KEY_FILE` at send time and honours `HTTPS_PROXY`. A message is retried up to five times (`attempts x 60 s` after creation) and then marked `failed` with an HTTP status or error class in `last_error`; inspect with:

```sql
SELECT id,purpose,status,attempts,last_error,created_at,sent_at FROM jobsearch.outbound_mail WHERE status<>'sent' ORDER BY id;
UPDATE jobsearch.outbound_mail SET status='queued',attempts=0 WHERE id=<id>;  -- requeue after fixing the cause
```

The mailer touches `JOBSEARCH_MAILER_HEARTBEAT` (default `/tmp/jobsearch-mailer-heartbeat`) after every successful pass and stops promptly on SIGTERM. Never print `outbound_mail.text_body` or `html_body` in shared channels: they contain live links.

## Cookies and origins

`/api/session` returns `links` (`JOBSEARCH_HUB_LINKS_PUBLIC` when the request host is on `JOBSEARCH_COOKIE_DOMAIN`, `JOBSEARCH_HUB_LINKS_LOCAL` otherwise) and `signup_enabled`. The session cookie is `HttpOnly`, `SameSite=Lax` by default, gets `Domain=<cookie_domain>` only on requests to that domain or its subdomains and `Secure` only over HTTPS (`X-Forwarded-Proto: https` from the gateway counts), so http://localhost:3105 keeps a host-only cookie. State-changing requests must carry an `Origin` from `JOBSEARCH_ALLOWED_ORIGINS`; `JOBSEARCH_HUB_ORIGINS` and `JOBSEARCH_LIBRARY_ORIGINS` replace the former hard-coded localhost ports. See [configuration](../configuration.md) for every variable and its default.

Use `./scripts/stack.sh status` for the isolated stack. Sign-in alone does not start the crawler scheduler. MFA is not implemented; public deployment still relies on the edge (Cloudflare Access, rate limits) described in the hub runbook. See ADR 0003 and ADR 0004 for limits.
