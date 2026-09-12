# Collection worker leases and separate scheduling

Status: implemented in source and integration-tested; production cutover is separate. This milestone does not deploy Kubernetes or enable external applications/email workers.

## Execution model

`python -m ai_core.agents.scheduler` queues due enabled sources and never collects them. A transaction-scoped scheduler lock and the existing active-source unique index prevent duplicate scheduling. `python -m ai_core.agents.supervisor` only consumes tasks; it no longer queues periodic work. Both support `--once` (scheduler: one scheduling pass; worker: at most one claimed task).

Workers claim individual PostgreSQL runs with SKIP LOCKED, an ownership UUID, an expiration and an attempt count. Heartbeats renew only an unexpired current token. Result writes lock and validate ownership before touching job observations, availability or completion; stale workers cannot overwrite a replacement's results. Collection failures store an exception class only, not arbitrary upstream content. Application records, archive locks and resume handling are unchanged.

The existing unique partial index enforces one active task per source. A PostgreSQL session advisory lock allows only one collection per provider at once, preserving conservative upstream concurrency while allowing different providers to run concurrently. No new provider request quota is inferred. Feed-specific enqueue cooldowns and deferred retries remain; crash reclamation also waits six hours for Remotive or one hour for Jobicy from the last attempt start. Network failures are not automatically requeued immediately; normal subsequent scheduling remains responsible.

This is at-least-once collection with fenced/idempotent database writes, not exactly-once HTTP execution. An HTTP request already in flight cannot be recalled. A hung process retaining its provider session can delay that provider until the session closes; the worker process has a finite run deadline. Do not use these collection leases as proof that employer submissions or SMTP delivery are safe to retry.

## Defaults and metrics

| Setting (JOBSEARCH_ prefix) | Default | Purpose |
|---|---:|---|
| WORKER_LEASE_SECONDS | 120 | Ownership renewal window |
| WORKER_HEARTBEAT_SECONDS | 20 | Renewal cadence; at most one third of lease |
| WORKER_MAX_RUN_SECONDS | 900 | Hard process deadline for one collection pass |
| WORKER_SHUTDOWN_SECONDS | 60 | SIGTERM drain budget |
| WORKER_MAX_ATTEMPTS | 3 | Maximum claims including crash reclamation |

SIGTERM stops further claims and allows the active run to finish. At the drain deadline the process exits 143, leaving its claim recoverable after expiration; the overlay grants 75 seconds before Docker force-kill. Graceful completion is preferred, but unbounded requests cannot hold shutdown indefinitely. Exit-code validation alone does not prove a run completed; inspect its durable state.

The worker progress file advances between tasks. A task longer than ten minutes can still trigger the existing health warning despite valid lease renewal; the 15-minute run deadline remains the hard bound. Scheduler progress has its own heartbeat file. API metrics now distinguish ready queue depth, running count and oldest queued age, alongside existing aggregate queue depth. These are measurements, not an installed autoscaler; backlog may include provider-limited tasks.

## Tests

Use only a disposable database named `jobsearch_auth_test`. Set JOBSEARCH_AUTH_TEST=1 and JOBSEARCH_DATABASE_URL to its owner DSN, then run:

```sh
JBS/bin/python scripts/test_database.py
JBS/bin/python -m pytest tests/test_worker_leases.py tests/test_collection_observability.py tests/test_intake.py tests/test_local_auth.py -q
```

The reset helper checks the connected database name before resetting its schema. It creates missing test roles; do not run it against shared databases other than the explicitly disposable test database. Tests use synthetic listings and mocked collectors, never employer forms or model APIs. Coverage includes concurrent provider execution, same-provider exclusion, lease renewal, expiration/fencing, bounded attempts, cooldowns, duplicate schedulers, process death and SIGTERM recovery, and existing private-data/archive regressions.

## Controlled production cutover (not executed by this milestone)

1. Back up the Jobsearch database. Keep the running image identifiers for rollback and verify no unrelated app changes are included.
2. Pause external refresh triggers; stop/drain the legacy worker. Resolve any legacy `running` rows from actual execution evidence. Migration 013 refuses a database with running rows; do not indiscriminately mark them failed merely to bypass the guard.
3. Apply `src/db/013_worker_leases.sql` to Jobsearch only using the migration owner. Existing runtime table-level permissions cover added columns; verify the worker's grants and no private-table access.
4. Build and start the API, worker and scheduler using both `compose.yaml` and `compose.worker-leases.yaml`. The base Compose file alone does not install the new scheduler. Do not mix legacy and leased workers or rebuild the worker with new source before migration and scheduler deployment.
5. Verify one scheduler, one worker, new queue metrics, a bounded collection and no repeated source tasks. Resume external refresh triggers. Only then consider additional workers with capacity and provider limits.

Current `scripts/stack.sh` uses base Compose and expects one container per service. It has not been adapted for the opt-in overlay or replicas. Before production cutover, update lifecycle/systemd integration to include the overlay and validate replica-aware service health; the overlay is currently for explicit staging commands only. Add scheduler scraping/alerts to the deployed monitoring configuration at that same cutover. Do not claim existing lifecycle commands manage the new scheduler.

Rollback requires stopping all leased workers and the scheduler, reconciling active leases, and restoring the old immutable worker image and scheduling owner. Added columns can remain; do not drop application data. Keep only one scheduling/execution generation active. Never roll back by starting a legacy worker alongside a leased worker.

## Validation record — 2026-09-12 UTC

110 database/collection/privacy/lifecycle regression tests passed, followed by two added targeted queue-metric and run-budget checks (112 distinct tests). The separate 21 learning/email unit tests also passed. The merged Compose overlay passed `config --quiet`; no services were started by that validation. Restricted worker-role execution was exercised against the disposable database. Two existing dependency deprecation warnings remain. Remote GitHub Actions results are not inferred from these local checks.

Production migration 013 was not applied, and no production container was rebuilt or restarted. All 12 Jobsearch containers reported healthy at verification. The library project was not modified.
