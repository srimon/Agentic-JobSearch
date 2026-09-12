> Current deployment decision: ADR 0002 supersedes all shared-service references below. Jobsearch uses separate PostgreSQL, Qdrant and Redis containers, credentials, volumes and networks.

# Data model and consistency

Logical design only. No DDL or migrations have been executed.

## Authority and isolation

PostgreSQL is authoritative. Use a `jobsearch` schema in the existing database with a migration owner and distinct runtime roles. Runtime roles must not create/alter schema or write library tables. Validate grants and search paths; do not rely on naming alone.

Qdrant contains rebuildable vectors in dedicated Jobsearch collections. Enforce access using supported scoped credentials or a gateway that validates collection access. Embedding model/version, dimensions and distance metric are explicit collection metadata. Redis requires ACL-enforced key/command restrictions or a gateway; prefixes alone are insufficient.

## Proposed entities

| Entity | Key information |
|---|---|
| users / user_roles | Trusted issuer + subject, active allowlist status, roles, change history |
| sources | Employer/ATS identity, canonical endpoint, policy state/version, check schedule |
| source_runs | Run status, complete/partial result, counts, error class, timestamps |
| source_snapshots | Source/run, object reference, content hash, retrieval time, access/retention class |
| jobs | Canonical job identity and current validated summary |
| listings | Source + provider posting ID, source URL, requisition, original title/location, availability |
| listing_observations | Listing/run, source version, observed fields, first/last observations |
| locations | Original text, normalized place/country, work mode, eligibility evidence |
| evidence | Snapshot reference, field name, quoted supporting span/locator |
| classification_decisions | Rule/prompt/model versions, match decision, reason, evidence, review status |
| job_links | Proposed/confirmed duplicate relationships and merge provenance |
| review_items | Ambiguity/conflict, assignee, resolution and evidence |
| saved_jobs / application_events | Owner user, job, personal status/notes and timestamps |
| tasks / task_attempts | Initiator, workload, parent, state, lease, budgets, idempotency key, failures |
| outbox_events | Transactionally committed work awaiting delivery |
| embedding_records | Job/content version, model/collection, point ID, index state |
| audit_events | Sanitized security events; independently controlled export |

## Constraints and semantics

- Unique user identity is `(issuer, subject)`; invitation email is not a trusted identity claim by itself.
- Listing identity uses source plus stable provider posting ID; normalized URLs are secondary evidence.
- Do not merge solely on title/company. Distinct requisitions and location variants can be legitimate.
- Every derived factual field links to evidence or is unknown. Preserve conflicts rather than choosing silently.
- `first_seen_at` and `last_seen_at` are collection timestamps, not employer posting dates.
- Salary preserves currency, interval, original range and source; do not invent annualized pay.
- Match status (`match`, `exclude`, `review`) is separate from availability (`observed_open`, `not_observed`, `confirmed_closed`, `unknown`).
- Persist UTC timestamps and model/rule versions. Retain transition history for closure, reopening and classification changes.
- Personal records enforce owner checks, with PostgreSQL row-level policies where adopted and tested. Operators do not automatically gain access to personal notes.
- Cross-source merge decisions must be reversible and traceable.

## Search and index lifecycle

Use SQL for exact filters and visibility. Semantic candidates from Qdrant are rechecked against current PostgreSQL authorization, match status and freshness before return. Stale vectors must not resurrect deleted/closed or inaccessible jobs.

On update, commit the listing/job change and outbox event in one transaction. An idempotent embedding worker indexes the specified content version. Reconciliation detects missing, obsolete or failed vectors. Model changes use a new collection/version and a validated cutover.

Raw payloads may contain hostile text and personal information. Store them as restricted evidence with integrity hashes, never execute/render raw HTML, and never log full payloads. Immutability means historical versions are not overwritten; controlled deletion for retention remains possible. Raw/processed/vector/audit retention periods and backup RPO/RTO are decisions still required.
