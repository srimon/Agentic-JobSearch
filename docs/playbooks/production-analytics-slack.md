# Production analytics Slack ownership

Production analytics runs in enterprise-hub/hub-workflows, CronJob
jobsearch-analytics. Its maintained deployment is in the canonical Hub's
scripts/jobsearch_analytics_notifications.py. The notification implementation
is Jobsearch-owned ai_core/tools/analytics_slack.py and is copied into the pinned
analytics image. Releasing it does not require restarting the Jobsearch API.

The Hub's owner-only .secrets/slack/config.json is the configuration source.
An explicit configuration sync puts webhook, enabled flag and policy into the
Jobsearch-owned jobsearch-analytics-slack Secret in hub-workflows. Pods receive
only that Secret's named fields; they do not mount the host filesystem or read
Library's Secret. Rotation requires running the sync again. Existing pods retain
their environment until they finish; do not interrupt an uncertain delivery.

PostgreSQL jobsearch.analytics_notifications records the Kubernetes Job UID
before sending. Replacement pods share the same UID and cannot send twice.
Only HTTP 200 with body `ok` is accepted; redirects are refused. Timeout, crash
or acknowledgement loss leaves `sending`/`unknown`; never delete those records
to force a retry. A new operator-created Job is a new event. Notifications contain
production scope, counts, run ID and bounded error class, never job text, profiles
or credentials. A failed notification does not invalidate a completed load.

The exact-host CONNECT proxy allows hooks.slack.com:443 only. Application direct
internet egress remains blocked. Slack policy `all` includes both outcomes;
`failures` suppresses successes; automatic_delivery=false disables sends.
Unavailable PostgreSQL prevents durable notification delivery, and pod scheduling,
image pull, termination or node failures can prevent Python from running. Those
failures require Kubernetes/Prometheus monitoring; worker notifications alone
cannot cover them.

scripts/slack_analytics.py and scripts/jobsearch_staging.py are historical staging
helpers, not this production pipeline. Staging transport now requires an explicit
JOBSEARCH_RETIRED_STAGING_KUBECONFIG and rejects the production context.
scripts/production_recovery.py is an old Compose rehearsal and must not be run to
recover the current cluster. Its wrapping key now uses the canonical Hub
.secrets/staging-backup.key; retired Compose services remain fenced.
