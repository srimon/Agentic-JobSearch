# In-app observability

Open `http://localhost:3105/?view=observability` with a Jobsearch operator or administrator account. The page embeds the **actual Grafana, Prometheus and Phoenix interfaces**, inspired by the library ToolPanel implementation. Chromadb files, services and data remain separate and unchanged.

## Views

- Grafana: Operations, API & Services, Collection & Decisions, Sources & Queue, and Logs. New dashboards default to 24 hours, refresh every 15 seconds, and support the real time picker, legends and panel drilldowns.
- Prometheus: preselected API traffic, latency, collection outcomes and queue graphs; query editor; targets; alerts; rules. Recording rules reference actual Jobsearch metrics.
- Phoenix: Projects & traces and the native GraphiQL explorer. Select the `jobsearch` project to inspect its execution traces. Monitoring asset/query traffic is excluded from new application traces so it does not drown out agent activity. Historical spans are not rewritten. The current collector records a source collection span, not an LLM conversation or proof of application submission.
- Expand enlarges the embedded interface; Reload returns to the selected screen; Open full view opens the same authenticated route separately.

Readiness is checked on arrival and every 15 seconds. A starting or unavailable service shows a retry message instead of an empty frame. Phoenix initialization may take about 90 seconds. Revoked or expired sessions lose access on the next check/request.

## Interpretation

Process CPU and memory graphs measure instrumented Python processes, not the host or every container. No library cAdvisor or database is used. Empty measurements remain missing; no model-quality scores are fabricated. Local Prometheus alerts are evaluated but no alert notification channel is configured by this change. Job report email is separate.

Logs are allowlisted structured telemetry from Jobsearch, not unrestricted Docker logs. Phoenix shows the actual stored spans and attributes; instrumentation must continue excluding request bodies, resumes, demographic answers, credentials and scraped content. Do not instrument private input/output text simply to populate the Phoenix UI.

## GraphQL

The authenticated endpoint is `/api/monitoring/phoenix/graphql`. The GraphQL explorer opens Phoenix's native Strawberry GraphiQL with a starter query:

```graphql
query JobsearchProjects {
  projects(first: 10) {
    edges { node { id name } }
  }
}
```

Use the explorer's documentation panel for the installed schema. Schema introspection and queries are allowed. Every operation in a submitted document must be a query; mutations and subscriptions are rejected, including mutations hidden in a multi-operation document or GET query parameter. WebSocket subscriptions are not supported. This is an operational read interface, not trace ingestion. The native GraphiQL page loads integrity-pinned assets from unpkg.com, so its editor requires browser access to that CDN; ordinary Phoenix assets are served locally.

## Access and isolation

`src/api/monitoring_ui.py` maps `/api/monitoring/{tool}/...` to fixed Jobsearch services. Each page, asset and API call requires operator authorization. The proxy strips browser cookies, does not forward user-supplied authorization, rejects unsafe paths/external redirects, and limits upstream responses to 32 MiB with connection/read timeouts. Only Grafana query/feature-evaluation POSTs and parsed Phoenix GraphQL queries are permitted. Other writes are blocked.

Grafana uses the server-side Viewer service account `jobsearch-panel`; its token never reaches the browser. Monitoring responses allow SAMEORIGIN framing with `frame-ancestors 'self'`; other API responses retain DENY. Vendor JavaScript runs on the trusted Jobsearch origin. This is explicitly not a separate sandbox. Avoid adding untrusted Grafana plugins or dashboards with executable content.

Grafana's existing loopback administrator endpoint on port 3106 remains authenticated. Prometheus and Phoenix have no published host ports. The normal portal exposes read-only access: some native UI write buttons may remain visible, but their requests are rejected.

## Deployment

Use `compose.yaml` plus `compose.worker-leases.yaml` via `scripts/stack.sh`. Root paths are configured for all three services. Build API/web, recreate only changed Jobsearch services, and allow Phoenix to become healthy. Prometheus recording rules require a Prometheus restart/reload; dashboard JSON files are provisioned from the bind mount. No library restart is required.

Keep `.secrets` owner-only (0700). The Grafana token remains owner-readable with a named ACL for API UID 10001: `setfacl -m u:10001:r .secrets/grafana_viewer_token`. Reapply that ACL if rotation replaces the inode; do not make the token world-readable. Phoenix uses its dedicated Jobsearch database and private credential file. Credentials, traces, logs and test sessions must not be committed.

The older `/api/observability/{tool}` read-only summary adapters remain available for diagnostics but are no longer the displayed monitoring interfaces.
