# Data Management navigation

Staging operators have a grouped Data Management menu. Analytics opens the authenticated ClickHouse console on localhost:3187/play. Quality entries select existing GX/Soda/dbt evidence; modelling keeps the SchemaSpy viewer and OpenMetadata catalog. Governance and lineage open OpenMetadata with a separate account; lineage ingestion is pending. Data Science and DAG scheduling are unconfigured placeholders. Ingestion links to existing discovery activity, not a new analytical ingestion pipeline.

Existing quality/model/governance deep links remain valid. New tool links use ?view=data-<tool>. No privileges, credentials, ingestion jobs, production routes or scheduler settings change.

The Notifications sidebar entry opens Slack workspace Sean, channel #general, using the owner-provided channel URL. The Slack app is ENTERPRISE-AI-HUB. These names were confirmed from the owner screenshot; webhook credentials are unchanged.

Production consolidation: JOBSEARCH_DATA_MANAGEMENT_ENABLED=true explicitly enables operator-only snapshot endpoints on the production database. Default remains disabled outside staging. This flag does not generate snapshots or claim quality checks ran; missing snapshots remain not_generated/empty. Snapshot schema and source-specific production pipelines must be deployed before final data-tool acceptance.
