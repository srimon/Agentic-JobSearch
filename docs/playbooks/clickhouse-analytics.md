# Jobsearch staging analytics

Scope: only Jobsearch files, jobsearch-pilot API/web deployments, the Jobsearch staging database and the Jobsearch-specific table in the existing ClickHouse service. No Hub portal or library redeployment, shared service configuration changes, new PostgreSQL instance or scheduler changes. The latest owner boundary takes precedence over older combined Hub deployment instructions.

## Pipeline and access

Run from /home/srimonadi/Jobsearch:

```bash
JBS/bin/python -m scripts.jobsearch_analytics
```

The explicit host-side operator command exports a repeatable-read snapshot of rows marked staging_public_feed (100,000-row safety ceiling). It projects UUID, source, provider, level, classification, availability, posting/observation timestamps and a SHA256 of the exact public URL. It excludes titles, descriptions, raw URLs, resumes, contacts, demographics and personal application/archival records. This is a public-feed analytical inventory, not an owner application queue. Source freshness statistics cover configured staging sources, including sources with no current listings.

A private Jobsearch .runtime ledger identifies changed rows. One batch per run for the current small feed (chunks capped at 10,000) appends new versions to hub_analytics.jobsearch_listings_v1. Removed source rows get tombstones. ReplacingMergeTree(version) with FINAL provides current identity semantics; no ALTER UPDATE/DELETE or OPTIMIZE FINAL occurs. Duplicate exact URLs are measured separately, not silently merged across distinct listing identities. The version is host UTC time in nanoseconds; host clock rollback requires operational review before ingestion.

ClickHouse aggregates are reconciled against the source count before publishing to jobsearch.analytics_snapshot in PostgreSQL. Runtime API role has SELECT only on the snapshot table. An interrupted run retains the last published snapshot; ClickHouse can contain newer partial rows until the next successful reconciliation. Missing local ledger plus source deletions causes reconciliation to fail rather than publishing a misleading snapshot. Recovery/rebuild tooling and long-term retention remain future work.

The pipeline uses the already configured operator client for the Jobsearch table; the API gets no ClickHouse admin credentials and no new network route. Existing hub_reader limits (30s, 512 MiB query memory, 1M scanned rows, 1,000 output rows, two query threads) constrain aggregates. The host command uses a privileged kubeconfig and is not an untrusted agent tool. A dedicated ingestion workload identity is required before production automation.

/api/analytics requires operator authorization and the staging database. Data Analytics > ClickHouse shows timestamped snapshots with a default 24-hour posting window, a 7-day option and all dates. Unknown posting dates are excluded from time windows. Dates use UTC and never substitute discovery time. Source/role charts are listing row counts; source freshness cards always cover all configured sources. Data older than 26 hours is visibly marked stale. Reload does not initiate ingestion.

Slack reports each explicit run's success/failure through the owner-configured webhook. Only summaries are sent. Jobsearch maintains its own duplicate-suppression journal; no Hub files are modified. There is no new schedule, no automatic source-feed hook and no production or MBK activity.

## Deployment and validation

JBS/bin/python -m scripts.deploy_jobsearch_analytics builds and patches only jobsearch-pilot deployment/api and deployment/web. Exact prior images are checked; protected workload specifications are compared before/after. Only the Jobsearch port-forward is restarted. Do not use the old combined Hub deployment script.

Initial live checks: 22 public source rows reconciled; repeated ingestion changed zero rows; Slack accepted both run summaries. EXPLAIN ESTIMATE reported one part, 22 rows, one mark. Unit tests exercise privacy projection, duplicate identities, incremental updates/removals, timezone validation, operator authorization, production rejection and notification deduplication/error handling.

## ClickHouse rules applied

- Per schema-pk-plan-before-creation and schema-pk-cardinality-order, ORDER BY(scope,job_id) uses the immutable low-cardinality scope then stable UUID. Mutable posting dates/roles must not enter the replacement identity. Date aggregates perform bounded scope scans, deliberately acceptable for this staging scale; no speculative skip index is added (query-index-skipping-indices).
- Per schema-types-native-types/minimize-bitwidth/lowcardinality, use UUID, UTC DateTime, UInt8 deletion flag and dictionary-encoded categories. Nullable posting time is semantically required (schema-types-avoid-nullable).
- Per schema-partition-start-without, no partitions for this small current-state table. Partitioning on mutable posting dates would break replacement semantics.
- Per insert-batch-size, batch changes instead of per-row requests; the 22-row initial feed is smaller than the preferred batch size, and is operator-triggered, not high-frequency. Async buffering is not required for this cadence.
- Per insert-mutation-avoid-update and insert-optimize-avoid-final, append versions and use SELECT FINAL without forced merges. Tombstones are logical reconciliation, not physical erasure.
- Per agent-discovery-schema and agent-query-safety, columns/keys/indexes/sample/EXPLAIN were inspected, schema reads are bounded and runtime profiles enforce scan, memory and output caps. Join and materialized-view rules are not applicable: no ClickHouse joins or MVs.
