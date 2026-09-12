# ADR 0002 — Separate Docker stack

Date: 2026-09-11. Status: accepted by the user; supersedes shared-service portions of ADR 0001.

## Decision

Use a Docker Compose project named `jobsearch` with dedicated PostgreSQL, Qdrant and Redis containers, credentials, persistent volumes and an internal data network. Reuse the technology choices and read-only reference patterns, not the library application's running service instances.

No Jobsearch service joins the library network or mounts its source/volumes. No library database migration or role change is required. Identical immutable image layers can be reused safely: each new container has its own writable layer and data volume.

The frontend/API/agents will be added to Jobsearch-owned deployment definitions. Publish only a reviewed frontend/gateway port when ready. Current data services publish no host ports. Local JBS commands cannot assume the library's localhost ports; use container execution or a separately reviewed loopback development override if later needed.

## Initial resource limits

PostgreSQL: 0.5 CPU, 512 MiB memory. Qdrant: 0.5 CPU, 1 GiB. Redis: 0.5 CPU, 256 MiB container limit, 128 MiB data limit with noeviction. These are initial development limits, not measured production sizing. Log files are limited to three 10 MiB files per container. Persistent-volume disk consumption is not capped by these settings and must be monitored.

Image digests are pinned to images already installed on the host, avoiding changes to library image tags or pulls during bootstrap. This is reproducibility, not a vulnerability assessment.

## Credentials and operations

Generate fresh random credentials under `.secrets/`, an owner-only directory excluded from Git. PostgreSQL reads its password file; Qdrant reads its API key from a mounted configuration; Redis reads its password from a mounted configuration. Containers need the files readable, so file-level modes may differ inside the private parent directory. Local Compose secrets are not an encrypted secret manager.

The bootstrap PostgreSQL owner is for administration/migrations only. A restricted runtime role remains to be created during application integration. Qdrant/Redis bootstrap credentials are not workload identities. Service-specific roles, workload identity, mTLS, WAF and Entra configuration remain implementation work. Plaintext protocols stay inside the private development network; this is not production transport hardening.

Use `scripts/stack.sh up`, `stop`, `status`, or `logs`. The wrapper fixes the project and file paths. It deliberately exposes no volume-delete/prune operation. Never use global Docker cleanup or all-container stop commands.

## Isolation limits

Docker projects still share the host kernel, Docker daemon, CPU, memory and disk. The host/Docker administrator can access resources. Internal networks and separate credentials reduce accidental coupling; they do not create a separate-host security boundary. A separate VM/host remains the stronger option.

Validate before/after library container IDs, start times, restart counts, mount paths and network memberships. Validate Jobsearch resources carry only the jobsearch project label, have no host port bindings and share no volumes/networks with the library. Check authenticated service access and rejection of unauthenticated requests.
