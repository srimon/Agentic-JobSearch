> Current deployment decision: ADR 0002 supersedes all shared-service references below. Jobsearch uses separate PostgreSQL, Qdrant and Redis containers, credentials, volumes and networks.

# Deployment and operations design

No resources have been provisioned by this documentation work.

## Reference stack observations

Read-only inspection on 2026-09-11 found the library's PostgreSQL 17/pgvector, Qdrant, Redis, FastAPI, scheduler, MCP, OpenTelemetry collector, Prometheus, Grafana, Tempo, Loki, Phoenix and cAdvisor containers. The frontend manifest declares Next.js 16.1.6, React 19.2.3, TypeScript, Material UI, Tailwind and Lucide. These are observed reference versions, not an approved Jobsearch dependency lockfile.

Observed host ports include PostgreSQL 5432, Qdrant 6333, Redis 6379, API 8000, MCP 9999, Grafana 3000, Phoenix 6006 and Prometheus 9090. The library startup script uses frontend port 3001 with fallback 3002. Recheck occupancy before choosing Jobsearch ports. Existing documentation was reported updated by the user to PostgreSQL; no SQLite migration is planned for Jobsearch.

## Intended topology

- Dedicated Jobsearch frontend, API, supervisor/agent workers, collector, scheduler, indexer and tool gateway processes.
- Separate networks for edge/API, agent execution, restricted external fetching and data access. Only required paths are allowed.
- Shared PostgreSQL/Qdrant/Redis endpoints accessed through scoped roles/ACLs or an enforcement gateway.
- A2A endpoints are internal. No public exposure of databases, worker management, identity issuer or raw evidence storage through Jobsearch.
- Reuse observability endpoints where permitted, with Jobsearch service labels, scoped access and sanitized payloads.
- A shared WSL/Docker host is a development environment, not a strong isolation boundary against a hostile host administrator.

Do not mount library source directories writable into Jobsearch. Do not mount the Docker socket into agent/collector containers. Workers run as non-root with minimal capabilities and bounded CPU/memory. Secrets are injected outside prompts and committed files.

## Startup and shutdown

Jobsearch-owned deployment definitions must reference existing services without taking ownership of library volumes or lifecycle. A Jobsearch shutdown must not stop shared stores. Readiness checks validate schema/version and required services without auto-migrating library data. Migrations run separately under the Jobsearch migration identity.

The initial queue proposal is Redis-backed delivery with PostgreSQL task/outbox state. Kafka exists in reference code but was not running during inspection; adopting Kafka is not required by this design.

## Observability and recovery

Use OTel correlation across API, A2A, tools and tasks. Track successful-source coverage, partial fetches, last successful run, review backlog, index lag, retry/dead-letter count, identity failures, guardrail decisions and model cost. No-data and all-sources-failed must be distinguishable.

Back up Jobsearch relational data and restricted source snapshots under a reviewed shared-database backup strategy. Restore drills must not overwrite library records. Qdrant should be reproducible from source versions, while snapshots may shorten recovery. Explicit RPO/RTO, retention and alert thresholds remain pending.

## Required choices before deployment

WAF/reverse proxy; OIDC provider and allowed users; workload identity issuer; secret manager; public/private hosting; external source/search providers; model/embedding choices; durable raw/audit storage; budgets/schedules; digest delivery destination. SPIFFE/SPIRE is a candidate, not installed infrastructure.

## Structure additions proposed, not created by this document

`frontend/`, `src/db/`, `src/guardrails/`, and `infra/` will contain the UI, migrations/repositories, controls and deployment assets when implementation is authorized. Existing Python/config/GitHub placeholders remain unimplemented.
