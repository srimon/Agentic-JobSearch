## Migration progress — 2026-09-13 17:20 UTC

Owner selected complete Kubernetes migration, including target and recovery validation, before switching traffic. The new jobsearch-production namespace baseline is deployed with restricted admission, default-deny networking and zero workloads/PVCs/services. No application data or traffic moved. Earlier findings below are historical.

Fresh Jobsearch-owned recovery rehearsal passed for both Jobsearch and Phoenix: all table contents, sequences and grants matched; encrypted records decrypted; unscoped private-row access was denied. The encrypted archive is retained in Jobsearch/.runtime/production-recovery, using the existing protected wrapping key read-only. Nothing was uploaded. The disconnected temporary recovery server was removed, and all production container identities/start times remained unchanged. The helper derives from Enterprise-AI-Hub/scripts/production_rehearsal.py at 5d62d2a with Jobsearch-only paths and local isolation helpers.

Shared-platform dependency: k3d-ai-hub-pilot-server-0 has cgroup memory.max=12884901888 (12 GiB), while Kubernetes capacity and allocatable both report 4294967Ki (about 4 GiB). Metrics reported 5216Mi usage (124%). Node Ready=True and MemoryPressure=False, but the capacity mismatch is unresolved. No shared node restart, cgroup modification or status patch was performed. The shared-platform owner must reconcile capacity and verify existing applications before production acceptance; do not fake node status to bypass this gate.

Still outstanding: production workload/service/storage and egress manifests; target-storage restore acceptance; production maintenance/write fencing and rollback; sole worker/scheduler/sender ownership; browser/native observability acceptance. The namespace baseline and successful isolated recovery do not complete those gates. Current production remains on Compose at 3105. Staging remains at 3185 and must not be deleted yet.

# Jobsearch-only production cutover status

Owner reauthorized production cutover on 2026-09-13 after successful staging validation. This does not authorize modifications to the shared Hub portal, autonomous library or MBK. Those boundaries remain absolute for this work.

## Verified 2026-09-13 17:12 UTC

- Analytics release 044b02a passed eight new regression tests, container frontend build/type checking, live snapshot reconciliation and anonymous HTTP denial.
- First ingestion reconciled 22 public listings; a second unchanged run inserted zero changed rows. The snapshot has 0 listings in the past 24 hours, 2 in seven days, and 22 across all dates.
- Jobsearch staging API/web were rolled out with protected workload specifications unchanged.
- All 14 production Compose containers are running and healthy.
- The cluster has no Jobsearch production namespace. jobsearch-pilot contains API/web/PostgreSQL and a staging PVC; it is not a production target.
- The Jobsearch repository has no production Kubernetes manifests. The existing analytics API explicitly rejects a production database and the export explicitly selects public staging provenance. A production analytics rollout needs a separate reviewed projection and scoped identity.

## Required work before traffic changes

1. Prepare the Jobsearch-only production target and its operational identity/network/storage boundaries without applying combined Hub deployment scripts. Reuse existing database services where safe rather than adding PostgreSQL instances by default.
2. Verify a current complete backup/restore, including application encryption keys, owner archives, external application outcomes, email journal, Phoenix and other nonempty persistent state. Earlier runbook evidence is historical, not a current freeze snapshot.
3. Validate maintenance/write fencing, drain conditions, one worker/scheduler/sender generation and rollback after new writes. Check both application scheduling and the external scheduled task.
4. Complete production login, archive-lock and native observability acceptance on the target, then execute a coordinated frozen migration and traffic switch.
5. Decommission staging only after successful production acceptance and recovery retention, never before.

No production traffic, writer ownership, scheduler, database, service startup or external application submission was changed by this analytics release. Do not infer that passing an analytics ingestion test establishes full production migration readiness.
