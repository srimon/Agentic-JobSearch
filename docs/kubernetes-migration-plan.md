# Enterprise AI Hub: inventory and Kubernetes migration plan

Date: 2026-09-11. Updated: 2026-09-12 UTC. Status: Jobsearch collector readiness and in-app monitoring deployed; Kubernetes platform remains proposed.

## Current milestone

The inventory and original blocking analysis below are historical observations. The collector scheduling/lease redesign has since been deployed with one scheduler and one worker; see `playbooks/worker-leases.md`. Jobsearch now has 14 configured services, including its own Phoenix, and operator-only Prometheus/Phoenix/Grafana panels. No Kubernetes migration or Library change has occurred. Reporting portability remains outstanding: `scripts/email_report.py` uses Docker Compose execution and a host delivery journal. Do not duplicate that sender in pods.

The next milestone is an isolated local Kubernetes pilot using synthetic state and disabled external actions. Before installation, run `JBS/bin/python scripts/migration_readiness.py`. It reports Docker capacity, Jobsearch health and tools on PATH without contacting Kubernetes, reading credentials, querying application records or modifying services. Missing measurements are unknown; the report never certifies production migration readiness. Tool presence does not establish that a usable cluster exists.

Remaining pilot choices: local distribution, NetworkPolicy-enforcing CNI, storage and recovery procedure, reserved ports, and representative resource budget. Production Compose continues to own all writes until staging and cutover gates pass. Keep PostgreSQL/Qdrant/Redis separate for the initial migration. The reporting rewrite can proceed independently but must pass durable ownership and uncertain SMTP-outcome tests before report scheduling moves.

## Scope and boundaries

The user selected a shared Kubernetes platform for Library (the chromadb/MBK project) and Jobsearch. Consolidate platform operations while preserving application access and data boundaries. This document does not authorize changing the library project, stopping its containers, merging data, or creating paid infrastructure. Existing isolation ADR 0002 remains the runtime rule until a controlled cutover is implemented.

Inventory used Docker list/stats and selected inspect metadata, source-file reads, filesystem capacity, and listener inspection. No secrets, environment values, database records, resumes, or book content were read. No lifecycle commands, application jobs, schema operations, or load tests were executed. Resource figures are one observation, not capacity measurements.

## Observed deployment

| Area | Jobsearch | Library / MBK |
|---|---|---|
| Running containers | 12 | 15 |
| Frontend | Next.js container, loopback port 3105 | Next.js documented at 3001; no frontend container in inspected Docker list; actual frontend process needs verification |
| API | FastAPI, private Docker network | FastAPI, published port 8000 |
| Worker/scheduler | One collector process schedules and executes work | Separate scheduler container; API executes RAG pipeline; MCP container also present |
| Relational store | Dedicated PostgreSQL | Dedicated pgvector/PostgreSQL 17 image |
| Vector store and cache | Dedicated Qdrant and Redis | Dedicated Qdrant and Redis |
| Monitoring | Grafana, Prometheus, Tempo, Loki, OTel, Alloy | Grafana, Prometheus, Tempo, Loki, OTel, Promtail, Phoenix, cAdvisor |
| Network boundary | data, frontend, observability, collector_egress networks | Inspected containers use mbk_default |
| Resource limits | Explicit memory limits on observed services | Inspected MBK containers report no explicit container memory limit |

Docker reports 16 CPUs and 33,504,272,384 bytes (~31.2 GiB) of available daemon memory. The WSL filesystem reports ~849 GiB available; this is not verified physical Windows-host capacity. No kubectl or k3s executable was found on the inspected WSL PATH; that does not prove no cluster exists elsewhere.

Snapshot examples: Jobsearch worker ~71 MiB, API ~59 MiB, Grafana ~277 MiB; Library API ~715 MiB, Qdrant ~453 MiB, Grafana ~710 MiB. CPU percentages were low in that snapshot. Collect at least a representative workload cycle, including ingestion, model calls, scheduled evaluations and reports, before setting production requests, limits or replica maxima.

All 12 Jobsearch containers reported healthy in the later status read. Several Library containers have no configured health check, so running must not be represented as healthy. The Library API uptime changed during inspection; no restart was initiated by this work, and the cause was not investigated.

Library publishes multiple infrastructure ports on all interfaces, including PostgreSQL 5432, Redis 6379 and Qdrant 6333. Firewall reachability was not tested. Jobsearch publishes only loopback 3105 and 3106. Gateway design must account for existing listeners before reserving ports.

## Storage and host dependencies

- Jobsearch uses named volumes for PostgreSQL, Qdrant, Redis, monitoring data and telemetry logs. Private intake has a read-only encryption-key mount. Migration requires coordinated backups and the correct key, never a key stored in Git.
- Jobsearch reporting also uses host files under data/processed and an owner-only email credential. These are outside an image-only migration and must be handled as private state.
- Library uses named volumes and host bind mounts for source, corpus, model cache, logs and the legacy SQLite placeholder. Its notes identify PostgreSQL as the actual relational backend; do not migrate the placeholder as the primary database.
- Library API mounts the Docker socket read-write. Kubernetes migration must replace Docker-management operations with narrow, authenticated operational APIs rather than mounting a runtime socket or giving the application cluster-admin.
- Corpus size, actual database/vector sizes, extensions, backup integrity, encryption-key recovery, volume ownership, Windows-host free space and retention requirements remain to be measured. No recovery guarantee is claimed.

## Blocking issues for horizontal agent scaling

### Jobsearch collector

Source: ai_core/agents/supervisor.py.

run_one acquires the same PostgreSQL advisory lock (74190315) for every run. Additional replicas would remain serialized. Its recovery logic marks all running runs failed after taking this lock; simply deleting the lock would let concurrent workers incorrectly invalidate one another. Scheduling also runs inside every worker loop. The source-code default schedule is six hours; this does not establish the deployed override or the separate desktop reporting schedule.

Required redesign before raising replicas above one:

1. Separate scheduling from execution, with one authoritative schedule and transactional enqueue deduplication.
2. Claim tasks transactionally using task-specific leases, heartbeat deadlines and fencing tokens.
3. Reclaim only expired claims. Require the current lease/fencing token when writing completion.
4. Preserve per-source exclusivity, source cooldowns, provider-wide rate limits and idempotent persistence.
5. Stop accepting new work on SIGTERM, drain within a defined termination budget, and leave recoverable claims if killed.
6. Export ready backlog, oldest-ready-task age, running claims, retries and provider throttling as safe metrics.

The existing queue is PostgreSQL, not Redis. Do not introduce a new broker merely to install autoscaling. Evaluate a narrowly scoped metrics exporter or compatible scaler against the existing queue first.

### Email and external actions

Source: scripts/email_report.py.

Reporting invokes docker compose exec and uses a filesystem flock/delivery journal. These dependencies are not portable to independently scheduled pods. Replace Docker invocation with a restricted internal API or service operation. Move delivery ownership to durable application state with atomic claims, a stable message identity and explicit accepted/unknown/failed outcomes. SMTP acceptance and DB acknowledgement are not one transaction; uncertain delivery must not trigger blind retries. Preserve existing archive and email-history behavior.

The separate Codex desktop automation is not transferred by deploying containers. Inventory its effective schedule and permissions before replacing it, disable the old owner only at cutover, and never run two active production schedules. This migration does not expand authorization for external applications or resume uploads.

### Library scheduler and RAG

Sources: scripts/scheduler.py, CLAUDE.md, src/promptops retrieval/stage modules.

Scheduler code checks last-start history and records jobs after execution; the inspected code does not establish a distributed claim across scheduler replicas. Keep one scheduler until durable execution ownership is implemented. Its daily/weekly jobs have potentially long timeouts and model cost limits that must survive migration. RAG includes in-process thread pools and a model cache: assess per-pod memory, cold starts, provider concurrency and timeout behavior before scaling API replicas.

## Proposed platform boundaries

| Namespace | Responsibilities |
|---|---|
| ai-hub | Portal, catalog, scoped operational API and hub metadata |
| library | Library frontend/API, MCP and application workers |
| jobsearch | Jobsearch frontend/API, scheduler and worker pools |
| identity | Shared identity provider with distinct application clients |
| observability | Redacted telemetry pipelines and authorized dashboards |
| platform-system | Gateway, certificates and required platform controllers |

Namespaces require enforced default-deny network policies, service accounts, resource quotas, restricted pod security and scoped secrets. Select a CNI that enforces NetworkPolicy. Grant egress deliberately; standard NetworkPolicy is not a hostname-aware web allowlist, so source-domain restrictions still need an application/proxy enforcement layer. Deny access to cloud metadata and infrastructure management endpoints as applicable.

Hub authentication does not replace application authorization. Integrate SSO one application at a time; preserve working local authentication until cutover. Keep private demographic/resume data out of shared telemetry. Agent tool permissions and prompt-injection controls stay enforced at the destination service. A2A integration is optional and must not bypass those controls.

Consolidate gateway, identity and observability first. Preserve separate PostgreSQL/Qdrant/Redis instances for the initial migration. Later evaluate shared PostgreSQL hosting with separate databases and roles, extension compatibility, connection pooling, contention tests and independently tested recovery. Sharing a server still shares its outage and maintenance boundary. Do not assume vector collections or Redis logical database numbers provide sufficient security isolation.

## Autoscaling plan

- Begin with one worker per application. Enable additional replicas only after concurrency and crash-recovery tests pass.
- Use HPA for stateless APIs after metrics and resource requests are configured. Use KEDA or an HPA external/custom metric for eligible queue backlog; choose one controller for each workload.
- Bound replicas by database connections, host memory, provider rate limits and model budgets. Add stabilization and cooldown to avoid oscillation.
- Scale finite tasks as Jobs only where their lifecycle and cancellation behavior are tested. Keep schedulers single-owner; worker replicas are not scheduler replicas.
- A single WSL host cannot autoscale physical capacity or provide host-failure availability. A multi-node platform and provisioning mechanism are separate later decisions. No paid cloud resources are authorized by this plan.

## Migration gates

1. **Discovery follow-up:** locate Library frontend process, verify effective schedules without revealing secrets, collect workload metrics, measure state sizes and define RPO/RTO. Deliver a capacity and dependency record.
2. **Worker readiness:** implement and test Jobsearch task claims, scheduler separation, recovery, and reporting portability in a disposable environment. Keep current production worker singleton.
3. **Platform pilot:** select a local Kubernetes distribution, CNI, storage and backup mechanism; reserve ports; deploy namespace/security baseline and hub. Keep production untouched. Decide recovery architecture before stateful workloads.
4. **Jobsearch staging:** build immutable images and deploy with synthetic fixtures, separate credentials, outbound email and employer submissions disabled. Do not mount live Docker volumes.
5. **Load/failure/security tests:** kill workers mid-task, repeat messages, simulate provider throttling and DB loss, test negative cross-application access, verify archives, and restore encrypted state in isolation. Acceptance includes no duplicated side effects and correct unknown-outcome handling.
6. **Jobsearch cutover:** take verified backups; pause the old scheduler, drain workers, synchronize final state, switch routing, enable one scheduler and verify login, lists, reports and monitoring. Record which deployment owns writes.
7. **Library migration:** requires explicit authorization to change library files/services. Adapt socket operations and host mounts; repeat staging and recovery gates before cutover.
8. **Selective service consolidation:** only after stable application migrations. Verify logical access separation, load contention and per-application restore procedures.
9. **Retirement:** retain old containers/configuration and protected backups through a defined rollback window. Delete volumes only with separate explicit authorization after recovery validation.

Rollback before new writes can restore routing to the old deployment. After new writes, blindly switching back would lose or duplicate state: pause writers, reconcile the new state and side-effect journal, then restore a single authoritative deployment. A successful rollout is not a backup test.

## Git and completion

Keep this discovery plan in the existing Jobsearch repository. A future AIHub repository will contain the platform implementation; neither application repository is merged by this document. Commit reviewed documentation and code increments without credentials or runtime data, push, and verify remote commit identity.

This milestone delivers an inventory and design only. No Kubernetes resources, shared databases, worker concurrency changes or library modifications have been deployed.

## Technical references

- [Kubernetes HPA](https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/): metrics-driven replica scaling and resource requests.
- [Kubernetes multi-tenancy](https://kubernetes.io/docs/concepts/security/multi-tenancy/): namespace boundaries and policy requirements.
- [Kubernetes NetworkPolicy](https://kubernetes.io/docs/concepts/services-networking/network-policies/): enforcement requires supporting networking.
- [KEDA scaling Jobs](https://keda.sh/docs/2.21/concepts/scaling-jobs/): event-driven finite task execution.


## Pilot preflight observation — 2026-09-12 UTC

The read-only preflight found 14 healthy Jobsearch containers. Docker reported 16 CPUs and 33,504,272,384 bytes of memory capacity (~31.2 GiB). The WSL filesystem reported about 848 GiB available. These are not measurements of spare physical host resources. kubectl, kind, k3d, k3s and helm were absent from PATH. No cluster was installed or contacted, and no services or schedules were changed. Four isolated preflight tests passed, including unavailable inventory, health ambiguity, command scope and error redaction. This completes a repeatable local inventory check, not the capacity, staging or production migration gates.


## Pilot configuration prepared — 2026-09-12 UTC

See `../infra/kubernetes/pilot/README.md` for the measured Windows/WSL snapshot, proposed ports, initial k3d/K3s choice, 4 GiB node limit, stateless namespace security baseline and installation gates. Configuration is prepared only; no cluster or resources have been deployed. The initial pilot has no PVCs or application credentials. Real NetworkPolicy enforcement and server-side admission tests remain required.
