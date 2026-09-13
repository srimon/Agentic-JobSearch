> Kubernetes migration progress: Jobsearch production namespace isolation baseline exists with no workloads. Fresh local Jobsearch/Phoenix restore passed. Shared node advertises 4 GiB despite its 12 GiB cgroup limit; platform-owner correction is required before production acceptance. No traffic or writer cutover yet. See docs/playbooks/production-cutover.md.

> Production cutover is reauthorized for Jobsearch only, but has not occurred. Live target-readiness findings and required gates are in docs/playbooks/production-cutover.md.

> Jobsearch-only staging analytics: see docs/playbooks/clickhouse-analytics.md. All new deployment work must target only Jobsearch; never use combined Hub/library rollout scripts.

> Resume intake update: encrypted owner-scoped intake and application evidence checks are implemented. See docs/playbooks/resume-intake.md. External application submission is not yet implemented.

> Authentication update: local administrator-created accounts replace external OIDC sign-in. See docs/decisions/0003-local-authentication.md and docs/playbooks/local-authentication.md (relative to the project root). MFA remains pending.

> Current deployment decision: ADR 0002 supersedes all shared-service references below. Jobsearch uses separate PostgreSQL, Qdrant and Redis containers, credentials, volumes and networks.

# AI context and workflow router

Status: architecture baseline, not deployed functionality.

## System summary

Next.js/React -> FastAPI -> scoped supervisor and A2A workers -> authorized tools -> PostgreSQL/Qdrant. Redis supports delivery, locks, and caching. A scheduler initiates bounded recurring runs. Guardrails cover ingress, external content, outbound calls, and outputs. User IAM and workload identity are distinct.

## Read by task

| Task | Primary context |
|---|---|
| Scope, service boundaries, collection workflow | `docs/architecture.md` |
| SQL, deduplication, vectors, freshness | `docs/data-model.md` |
| Authentication, A2A, tool calls, guardrails | `docs/security.md` |
| Containers, networks, shared services | `docs/deployment.md` |
| Verification and regression tests | `docs/evaluation.md` |
| Failures, containment, restoration | `docs/playbooks/operations.md` |
| Accepted choices and pending choices | `docs/decisions/0001-architecture-baseline.md` |

## Workflow

Discover -> policy-check source -> collect -> preserve snapshot -> inspect content -> normalize -> classify -> resolve identity -> validate evidence -> persist -> index -> serve validated output.

No model gets unrestricted SQL, shell access, credentials, or authority to register trusted sources/agents. Verified user/workload identity and server policy determine permissions; payload fields do not.

Feedback ranking is implemented: see docs/playbooks/feedback-learning.md for bounded weights, versioning and pause/reset/restore controls.
