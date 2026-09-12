# Collection operations

The `worker` Compose service runs the deterministic collector and scheduler, checking enabled boards every six hours. It uses a dedicated database login with no access to users, password hashes, or sessions. It shares only Jobsearch networks and exposes no host port.

Initial boards: Headway, Homebase, Qualified Health, 9amHealth (Ashby public posting feeds). These are a small pilot, not comprehensive internet coverage. Source registration supports Ashby, Greenhouse and Lever. Operators can queue a refresh from Sources; Activity shows completed/failed runs and candidate counts. The Refresh button on Opportunities reloads stored results; it does not crawl the internet.

Use Any time to inspect all currently observed matching roles. Date windows exclude missing timestamps. Ashby's publishedAt is the source's last publication date and may reflect republishing, not original creation. US country evidence is required; unknown locations go to review and non-US locations are excluded. Source failures do not mark previous postings closed. A successful refresh marks absent jobs not_observed, rather than claiming confirmed closure.

Source requests use fixed ATS hostnames, public-IP validation, TLS, response limits, no redirects and bounded retries. Network-level destination enforcement, secured A2A, model reasoning and Qdrant indexing are not yet implemented. The worker is a deterministic scheduler/collector, not the complete multiagent architecture.

Container health uses a progress timestamp refreshed between source runs and idle loops. Staleness over ten minutes fails health checks; Docker health status alone does not restart an unhealthy process. Process exits use the existing restart policy. Lifecycle startup/shutdown logs include worker health and library isolation comparison.

Verification: collection unit tests cover role scope, both expanded CDO meanings, unknown dates, non-US exclusion, alternate US locations, private DNS destinations and credential-bearing content exclusion. Live counts must come from database runs, not search-engine snippets.

## Current role criteria (2026-09-11)

Include Director, Senior Director, VP and SVP titles with explicit data, analytics, business intelligence, information management/governance, AI, artificial intelligence, machine learning or generative AI functions. Also include CTO, CIO, Chief Data Officer, Chief Digital Officer and Chief AI Officer (including CAIO). Bare CDO remains in review until its meaning is established. Generic engineering/technology leadership alone does not qualify.

Specialized scientific discovery/design titles (such as AIRx Director, Computational & AI Biologics Design Lead) are excluded unless they explicitly identify a data function or an approved chief officer role. A pharmaceutical employer alone is not an exclusion. Ambiguous supporting, field, sales or marketing titles go to review. These deterministic title rules are a conservative approximation, not a verified assessment of full responsibilities. US eligibility and content guardrails still apply.

## Worker scaling source update

Leased worker and standalone scheduler were deployed on 2026-09-12 UTC with one worker. Read [worker leases](worker-leases.md) before rebuilding or deploying the collector. Migration 013, the opt-in Compose overlay, lifecycle integration and a controlled drain are required. The earlier combined-worker description above describes the superseded deployment.
