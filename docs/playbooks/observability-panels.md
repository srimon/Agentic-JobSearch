# In-app observability

Open Observability in Jobsearch. Operator and administrator roles can select Prometheus, Phoenix or Grafana without leaving the page. These are native read-only views, not the complete vendor administration consoles.

The active panel refreshes every 30 seconds while visible. Refresh now requests fresh upstream data. Prometheus scrapes every 15 seconds; Grafana charts cover one hour. Missing measurements remain unavailable, not zero. Individual Grafana query failures are marked unavailable. An expired session clears displayed data.

Prometheus shows queue history and Jobsearch scrape targets. Grafana uses the provisioned Jobsearch Operations dashboard titles with server-allowlisted Prometheus queries through Grafana. The raw logs panel is excluded. Phoenix shows the latest 25 Jobsearch traces with only IDs, names, times, durations, span counts and outcomes. UNSET is not a success claim. No application-submission or model-quality result is inferred from a trace.

The API permits only fixed read-only tool routes, rejects redirects, bounds response sizes and timeouts, and never exposes service credentials. Grafana uses the Viewer service account jobsearch-panel; its token is mounted from .secrets/grafana_viewer_token. Rotate through the Jobsearch Grafana administrator UI, replace this private file and recreate the API container. Never place the token in source control or frontend configuration. Viewer access is broader than an individual dashboard; the API further restricts paths and queries.

Jobsearch Phoenix is an isolated container with no published port and a dedicated jobsearch_phoenix database and role on Jobsearch PostgreSQL. Its credential is in .secrets/phoenix.env. Include that database and credential in private backup and restore procedures separately from the jobsearch application database. OTLP traces are delivered to both Tempo and Phoenix. Library/chromadb services are not connected or modified.

Deployment uses compose.yaml plus compose.worker-leases.yaml via scripts/stack.sh. All 14 configured services are checked by the lifecycle wrapper. Phoenix initialization can take about 90 seconds. Source checkout deployment requires both private Phoenix and Grafana credentials to be provisioned first; these are intentionally absent from Git.

## Credential file permissions

Keep .secrets owner-only (0700). The Grafana token is owner-readable and grants read access specifically to API UID 10001 using `setfacl -m u:10001:r .secrets/grafana_viewer_token`; group and other access remain absent. Reapply this named-user ACL if rotation replaces the inode. Do not make the token world-readable.

## Verification

The monitoring adapter suite has nine passing tests covering unauthenticated/member denial, fixed tools and queries, output redaction, missing metrics, individual failures, redirects and response-size limits. The frontend production build passed. Browser checks with synthetic API fixtures passed for all three panels, manual/automatic refresh, pausing, trace expansion and mobile layout. Live upstream verification returned three Jobsearch scrape targets, nine Grafana panels with no query failures, and a new operational trace in Phoenix. All 14 configured services passed lifecycle health checks; the library comparison was unchanged.
