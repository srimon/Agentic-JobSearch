> Current deployment decision: ADR 0002 supersedes all shared-service references below. Jobsearch uses separate PostgreSQL, Qdrant and Redis containers, credentials, volumes and networks.

# ADR 0001 — Architecture baseline

Date: 2026-09-11. Status: requirements accepted in conversation; implementation not started.

## Accepted requirements

1. US executive job discovery/monitoring, both Chief Data Officer and Chief Digital Officer.
2. React frontend; use the reference Next.js/FastAPI stack as the design baseline.
3. Existing PostgreSQL database and Qdrant service, with Jobsearch-specific data and access boundaries.
4. Multiagent implementation with secured A2A communication and workload identities.
5. WAF, IAM, explicit allowed users, input/content/output guardrails, controlled egress and tool-call audit.
6. Preserve the requested directory structure; reference chromadb is strictly read-only.

## Proposed implementation decisions

- PostgreSQL-native repositories and versioned migrations; no SQLite compatibility adapter.
- Dedicated jobsearch schema/runtime roles; dedicated Qdrant collections with enforced access.
- Redis queue/locks with PostgreSQL task state and transactional outbox.
- Deterministic execution and validation; models interpret ambiguity and propose evidence-backed results.
- A2A for deployed agent boundaries; deterministic workers remain ordinary services where appropriate.
- Mandatory controls fail closed at the affected action boundary; validated facts may still be served when optional generation fails.
- Jobsearch-owned processes/configuration, independently stoppable from the library stack.

## Consequences

Shared infrastructure reduces duplication but introduces availability/resource coupling; quotas and tested isolation are necessary. More identities and policy enforcement increase operational work. A2A does not supply an identity issuer or remove authorization responsibilities. Qdrant indexing is eventually consistent and must be reconciled against PostgreSQL.

## Open decisions

| Decision | Status |
|---|---|
| WAF/reverse proxy and OIDC provider | Unselected |
| Workload identity issuer | SPIFFE/SPIRE candidate; unselected |
| A2A SDK/protocol version | Pin during implementation |
| Search providers and initial employer/source inventory | Unselected |
| Models, embeddings and quality thresholds | Baseline required |
| Hosting/network topology and port assignments | Unselected |
| Audit/raw storage, retention, backup targets | Unselected |
| Schedule, concurrency and cost budgets | Unselected |
| Allowed users, roles and MFA policy | Unconfigured |
| Digest notifications | Destination and send authorization pending |

Do not interpret acceptance of architecture as authorization to deploy, send messages, change library services or provision paid products.
