-- Current-listing identity is immutable; mutable posting dates cannot be replacement keys.
CREATE TABLE IF NOT EXISTS hub_analytics.jobsearch_listings_v1 (
 scope LowCardinality(String) COMMENT 'Always jobsearch_staging',
 job_id UUID COMMENT 'PostgreSQL public listing identity',
 source LowCardinality(String), provider LowCardinality(String), level LowCardinality(String),
 match_status LowCardinality(String), availability LowCardinality(String),
 posted_at Nullable(DateTime('UTC')) COMMENT 'NULL means employer posting date unknown',
 last_seen_at DateTime('UTC') COMMENT 'Observation time, never posting date',
 url_hash FixedString(64) COMMENT 'Exact public URL SHA256 for duplicate diagnostics',
 deleted UInt8, version UInt64
) ENGINE=ReplacingMergeTree(version) ORDER BY (scope,job_id)
