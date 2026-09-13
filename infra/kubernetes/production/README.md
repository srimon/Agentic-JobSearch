# Jobsearch production target

The namespace is distinct from public staging. The baseline enforces restricted admission, denies ingress/egress and disallows LoadBalancer/NodePort exposure. The quota is an upper bound, not a reservation or proof of available node capacity. No application workload, storage claim, runtime secret, worker or scheduler is activated by this baseline.

## Cutover prerequisites

- Reconcile shared node advertised capacity with its real cgroup limit before accepting production scheduling. This is shared-platform work and cannot be performed by the Jobsearch-only deployment agent.
- Build and validate complete Jobsearch workload/service/storage and egress manifests. Preserve production monitoring state and native authenticated paths.
- Restore and verify a rehearsal inside the eventual production storage path before cutover. Reuse one PostgreSQL service for Jobsearch and Phoenix, using the existing pinned PostgreSQL image version.
- Test maintenance/write fences, lease drain, sender ownership and startup behavior. The old and new scheduler must never both claim work.
- Preserve the authoritative production state and encryption keys. Never relabel the public staging database as production.

The current Compose deployment remains authoritative. This baseline is not a completed migration or permission to switch traffic.
