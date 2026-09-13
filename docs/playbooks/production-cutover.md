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
