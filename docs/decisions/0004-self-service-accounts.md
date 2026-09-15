# ADR 0004: Self-service accounts

Accepted 2026-09-14. Extends ADR 0003. Local accounts stay the only identity; the hub is now public as bagala.ai, so people must be able to register, confirm an address and recover a password without the operator console.

## Decision

Sign-up (`POST /api/auth/signup`) creates a local account with `issuer='local'`, the roles in `JOBSEARCH_SIGNUP_DEFAULT_ROLES` (default `viewer`), the same username rules and Argon2id hashing as ADR 0003, and an unverified email address. The endpoint exists only while `JOBSEARCH_SIGNUP_ENABLED=true`; otherwise it answers 404. A self-registered account cannot sign in until its address is confirmed; console-created accounts have no address and sign in as before. Giving such an account an address through the console (`email USERNAME EMAIL`) makes verification mandatory too, and `verify USERNAME` confirms it without mail.

Email verification is the only proof of ownership. A password reset link also proves control of the address, so a successful reset marks the address verified and signs out every session. Changing the address in the profile clears verification and queues a new link; the account keeps its current session but cannot sign in again until the new address is confirmed.

## Enumeration safety

Anonymous endpoints answer identically whether or not an account exists: sign-up, resend and reset-request return `202 {"detail":"check your email"}` for a new, duplicate, unknown, disabled or already verified account; verify and reset return `400 {"detail":"invalid or expired token"}` for unknown, used and expired tokens alike; a profile update to an address another account already uses returns the same `200 {"ok":true}` as a successful change and leaves the address unchanged. Only `audit_events` records the difference (`allowed`, `duplicate`, `ignored`, `queued`, `denied`, `throttled`, `unverified`), and audit rows never contain an address, a token or a password. The one deliberate exception is a correct password on an unverified account, which answers `403 Verify your email address before signing in.`; the caller has already proven the password.

## Tokens

Tokens are 32 random bytes (URL-safe base64), sent once in a link (`{public_origin}/?verify=<token>` or `/?reset=<token>`) and stored only as a SHA-256 digest, like sessions. They are single use, expire after 24 hours (verify) or 1 hour (reset), and only one live token per purpose exists per account: issuing a new link retires the previous one, so a link mailed to an old address cannot confirm a new one. Expired tokens and `login_limits` rows older than a day are pruned inside the login transaction with `SKIP LOCKED`, so no separate housekeeping job exists and the lock order between requests stays acyclic.

## Rate limits

The `login_limits` table and its fixed 15-minute windows cover every new endpoint: sign-up 30 attempts globally and 5 per address, mail requests (resend and reset-request together) 60 globally and 3 per address, password changes 10 per account. Login keeps 100 globally and 10 per username. Buckets count attempts regardless of whether the account exists, and a throttled request answers `429` with `Retry-After: 900` after committing the counter and audit row. As in ADR 0003 these are application budgets that bound hashing and mail volume; they do not replace edge rate limiting and can be used to deny service to one address.

## Mail

Mail is queued durably in `jobsearch.outbound_mail` inside the same transaction as the account change and delivered by `scripts/mailer.py`, a single replica polling every 10 seconds that commits each row on its own. `JOBSEARCH_MAIL_TRANSPORT=log` (default) only prints `{"event":"mail.sent","purpose":..,"to_domain":..}`; `resend` posts to the Resend API with `urllib` (which honours `HTTPS_PROXY`), reads the key from `JOBSEARCH_RESEND_API_KEY_FILE` at call time and sends an `Idempotency-Key` per row so a retry after a lost response cannot duplicate a message. A failed attempt records an HTTP status or an error class, never the provider body, and is retried after `attempts x 60 s`; the fifth failure marks the row `failed` for inspection. Logs and the database never contain the key or an address's local part.

## Cookies and origins

The session cookie now defaults to `SameSite=Lax` so a link from the hub, library or prep site to Jobsearch arrives signed in; `Strict` dropped the cookie on every cross-site navigation. The same API serves `http://localhost:3105` and `https://jobs.bagala.ai`, so cookie attributes are decided per request: `Domain=<cookie_domain>` only when the request host is that domain or a subdomain of it, `Secure` only when `secure_cookies` is on and the request arrived over HTTPS (its own scheme or the gateway's `X-Forwarded-Proto`). Logout deletes the cookie with the same decision. Trusting `X-Forwarded-Proto` here can only add the `Secure` flag; a forged header on a plain-HTTP request yields a cookie the browser refuses. The CSRF check still requires an exact `Origin` match but against the `allowed_origins` list; `hub_origins` drives the `/api/workflow` CORS grant and `library_origins` the library gateway, replacing hard-coded localhost ports. `/api/session` returns `links` (public or local hub links chosen by request host) and `signup_enabled` so the front end never hard-codes hosts.

## Not implemented

No MFA, CAPTCHA, breached-password screening or device notifications; no edge rate limiting inside the application; no delivery tracking beyond provider acceptance. Sign-up is off by default and the platform release enables it together with the mailer, the Resend key mount and the origin lists.
