# Local authentication operations

Run from `/home/srimonadi/Jobsearch`. The application must be running.

Create the first administrator (choose your own username):

```bash
./scripts/account.sh create admin --name "Jobsearch Administrator" --roles administrator member operator
```

The command prompts twice for a 15-128 character password without displaying it. No default password, public signup or browser bootstrap endpoint exists. Do not put passwords in command arguments or chat.

Open http://localhost:3105 and sign in with that account.

```bash
./scripts/account.sh create anotheruser --roles member
./scripts/account.sh reset admin
./scripts/account.sh disable anotheruser
./scripts/account.sh enable anotheruser
./scripts/account.sh revoke admin
```

Reset, disable, enable and revoke invalidate all existing sessions for the user. A reset does not re-enable a disabled account. Account creation rejects duplicates. Audit records contain actions and account IDs, not password values. Trusted local OS/Docker access authorizes the console; anyone with Docker access is already a host administrator equivalent.

Use `./startupdocker.sh`, `./stopdocker.sh` and `./scripts/stack.sh status` for the isolated stack. Startup/shutdown health checks now discover API and web alongside the database services. Sign-in alone does not start the crawler scheduler.

MFA and Internet-facing deployment controls are not implemented. Keep this deployment local. See ADR 0003 for limits.
