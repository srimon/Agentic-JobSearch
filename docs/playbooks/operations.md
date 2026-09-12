> Current deployment decision: ADR 0002 supersedes all shared-service references below. Jobsearch uses separate PostgreSQL, Qdrant and Redis containers, credentials, volumes and networks.

# Operational playbooks

Design procedures, not executable commands. Apply only within authorized Jobsearch scope.

## Source failure

Record complete/partial/error state and last successful check. Preserve existing availability. Honor source retry limits; move repeated failures to operator review. Resume from durable task state. Never report a failed source as zero open jobs.

## Suspected prompt injection

Quarantine the affected snapshot/proposal, retain restricted evidence, and record rule/policy/task IDs without copying raw content into logs. Block unauthorized tool actions regardless of classifier confidence. Review and add a sanitized regression fixture before release.

## Compromised agent or credential

Disable the workload identity and its delegations, halt its new tasks, rotate affected credentials and review audit/resource access. Reconcile in-flight writes and derived vectors before replay. Do not restart or alter shared library services as an automatic response.

## Identity, policy or audit outage

Stop affected new protected actions. Preserve pending work and durable intent records. Permit degraded reads only under explicit policy. Verify recovery and reconcile outcomes before resuming workers.

## Index inconsistency

Serve authorized SQL-backed results with semantic search marked degraded. Rebuild/reconcile only Jobsearch collections from versioned records. Verify permissions and metadata before switching collection aliases or references.

## Data restoration

Restore into an isolated target first; verify counts, ownership, evidence links and task state. Review any shared-database operation for library impact. Rebuild derived indices as needed. Replay work idempotently and reconcile audit events.

## Release readiness

Review architecture decisions, lock dependencies, run scope-appropriate tests, verify user/workload permissions and source policies, confirm secrets/audit redaction, inspect migration impact, and define rollback. No public release until origin bypass, internal-service exposure and mandatory failure behavior have been tested.
