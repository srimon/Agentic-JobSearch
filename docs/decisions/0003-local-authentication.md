# ADR 0003: Local authentication

Accepted 2026-09-11. Supersedes Google and Entra user sign-in plans.

Use administrator-created local usernames, Argon2id password hashes (64 MiB, three iterations, one lane), and opaque server-side sessions. No public registration or external identity credentials. User identity is issuer `local` plus a normalized username. Passwords contain 15-128 characters; no arbitrary composition rules. No passwords are created by deployment.

The browser receives an HttpOnly SameSite=Strict cookie; the database stores only its SHA-256 digest. Sessions expire after eight hours. Active status is checked on every authenticated request. Console password resets, enable/disable and revoke operations delete all that user's sessions. Login uses generic errors and durable audit events. Validation responses do not echo submitted credentials.

PostgreSQL enforces 10 login attempts per username and 100 globally per fixed 15-minute window, including successful attempts. Row locks enforce limits across replicas. The global limit intentionally bounds hash computation and arbitrary username storage for a private application; it also permits denial of login by an attacker and is not a substitute for edge rate limiting. Failed and throttled attempts commit before errors are returned. State-changing requests require the configured exact Origin. No forwarded IP headers are trusted.

Initial deployment publishes only 127.0.0.1:3105. Plain HTTP cookies are for localhost development only. Public deployment requires HTTPS, secure cookies, host validation, WAF/edge limits and a reviewed threat model. This implementation does not include MFA, recovery codes, breached-password screening, tamper-resistant audit export or secured A2A workload identity. Optional MFA remains future work, not a shipped feature.

Runtime uses a separate PostgreSQL role. Audit events permit INSERT and SELECT but no UPDATE/DELETE for that role. Database/Docker administrators can still modify data. Current API role can manage local accounts for the operator console; split console privileges before public deployment. No library database, volumes or accounts are used.
