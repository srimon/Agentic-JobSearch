> Authentication update: local administrator-created accounts replace external OIDC sign-in. See docs/decisions/0003-local-authentication.md and docs/playbooks/local-authentication.md (relative to the project root). MFA remains pending.

> Current deployment decision: ADR 0002 supersedes all shared-service references below. Jobsearch uses separate PostgreSQL, Qdrant and Redis containers, credentials, volumes and networks.

# Security architecture and permission matrix

Design baseline; controls described here are not yet implemented.

## Threat model

Untrusted actors include anonymous visitors, authenticated users outside a resource's permissions, malicious websites/postings, compromised agents, forged agent endpoints and leaked credentials. Protect user records, shared library infrastructure, model credentials, job-data integrity and compute budgets.

Trust boundaries: browser-to-edge; edge-to-API; API-to-agent; agent-to-agent; agent-to-tool; crawler-to-internet; application-to-shared stores; application-to-audit destination. Trust in transport identity does not make content trustworthy.

## User IAM and WAF

Authenticate through a selected OIDC provider; use a server-side session/BFF with secure HttpOnly cookies, CSRF protection and explicit origin policy. Enforce token/session validation and resource authorization in the backend. Require trusted issuer/subject in the active allowed-user list. Disable access promptly on removal; define session revocation and revalidation.

| Role | Allowed operations |
|---|---|
| Viewer | Search/view validated public job records |
| Member | Viewer operations plus own saved jobs/application records |
| Operator | Source refresh, review decisions and operational run inspection |
| Administrator | Allowlist/role/policy/budget administration |

Roles may be combined explicitly. Administrator/Operator does not implicitly mean unrestricted private-note access. Require strong authentication for privileged actions; provider selection and MFA policy remain open.

WAF/HTTPS ingress applies request limits, common web-attack rules, rate controls and origin restrictions. Prevent direct origin/API bypass. WAF does not replace injection defenses, authentication, schema validation or authorization. Private A2A and data services must not be publicly exposed.

## Workload identities and A2A

Issue a distinct identity per separately deployed workload using an attesting identity issuer. SPIFFE/SPIRE is a candidate, not a selected deployment. Certificates/tokens must be short-lived, rotated and validated; revocation/disable behavior must be tested. Container names and payload `agent_id` fields are not authentication.

- Production A2A uses HTTPS; the Jobsearch design requires mTLS between agent services plus operation/resource authorization.
- Maintain a trusted registry of agent endpoints and Agent Cards. Cards describe capabilities, not trust grants.
- Authorize create/read/cancel/stream/artifact operations independently and enforce task ownership.
- Validate credential issuer, audience, lifetime and intended peer. Use scoped delegation when acting for a user; do not forward a general user session token across agents.
- Effective authority is the intersection of initiator authority, delegated scope, receiving workload permissions and resource policy.
- Apply deadlines, idempotency/deduplication and request limits. Idempotency does not replace token replay protection.
- Keep authentication in the verified transport/security layer. Trace IDs and payload user IDs are correlation data only.
- Disable external callbacks initially; any later callbacks/artifact fetches require destination validation, authentication and replay controls.
- Pin and test a compatible A2A protocol/SDK version before implementation.

## Agent/tool permission matrix

| Workload | Allowed capability | Denied by default |
|---|---|---|
| Scheduler | Start predefined schedules under service policy | User impersonation, arbitrary tasks |
| Supervisor | Delegate bounded tasks, inspect authorized results | Direct shell, SQL, credential reads, policy grants |
| Discovery | Approved search tools; propose source records | Trust arbitrary domains or agents |
| Collector | Fetch source-policy-approved public endpoints | Internal/metadata endpoints, model credentials, library writes |
| Extractor/classifier | Read sanitized assigned snapshots; propose facts | Publish records, change access rules |
| Verifier | Validate assigned proposals; request controlled publication | Override failed mandatory controls |
| Data service | Named parameterized operations on permitted records | Library schema writes, caller-supplied SQL |
| Indexer | Read authorized content versions; write Jobsearch vectors | Other collections, user access changes |
| Digest worker | Read validated permitted jobs; prepare digest | Sending before delivery authorization/configuration |

The tool gateway enforces authenticated workload, delegated scope, operation/argument schema, resource ownership, destination, budget, timeout and audit prerequisites. Agents receive results, not provider secrets. Policy checks are deterministic and outside model control. Secrets come from a chosen secret-management mechanism; rotation and scoped storage access are required.

## Prompt injection and content ingress

Inspect user input, crawled text, search snippets, retrieved passages and A2A artifacts. Keep evidence separate from instructions. Detect suspicious instruction patterns, hidden content and secrets; sanitize HTML and constrain sizes/types. Quarantine suspect evidence rather than automatically execute or blindly discard legitimate job facts.

Injection detectors are fallible. Even a compromised model must lack permission to exfiltrate credentials, change policy, invoke shell, execute arbitrary SQL or contact arbitrary hosts. Test indirect injection through retrieval and agent-to-agent artifacts. Prompt/system-text secrecy is not an authorization boundary.

## Egress

Separate internal service routing from public crawling. Enforce public URL policy before connection and every redirect; reject local/private/link-local/metadata addresses, unsupported schemes, embedded credentials and invalid destinations. Account for DNS changes, IPv6 and redirects; enforce destination policy at connection/proxy level rather than only parsing a hostname once.

Use source-access rules, bounded redirects, byte/time limits, concurrency controls, retry-after handling and request budgets. The model gateway restricts providers/models, redacts sensitive content and applies spend limits. Direct bypass from workers must be blocked by network policy. Source discovery can propose endpoints; activation requires deterministic policy or operator review.

## Output and failure policy

Validate schemas, provenance, job URL, US eligibility, factual evidence, sensitive information and freshness before publication. Unsupported salary/sponsorship/availability claims remain unknown. HTML is escaped/sanitized at presentation.

Mandatory authorization, destination, secret-protection and publication checks fail closed. Hold affected operations on failure. Optional summary/moderation outages use an explicit policy: return independently validated source facts or flag/hold the generated portion; do not silently publish unchecked generated content. Low confidence cannot override failed evidence checks.

## Auditing

Record authentication failures, role/allowlist/policy changes, delegation, task lifecycle, tool attempts/denials/outcomes, exports and guardrail decisions. Capture event ID, UTC time, verified initiator/workload, task/parent/trace/call IDs, tool version, sanitized resource/argument summary, policy version/decision, outcome/error class, duration and applicable model/prompt/usage metadata.

Do not log secrets, raw credentials, unrestricted prompts, private notes or full crawled pages. Keep restricted evidence separately referenced. Application audit writers cannot update/delete prior events. A PostgreSQL append-only table is not tamper-proof against its administrator; export to an independently administered, retention-protected destination for stronger assurance. Retention and access rules remain to be selected.

Security auditing is unsampled; traces may be sampled. Auditable state-changing and external tool actions require durable intent recording before execution and outcome reconciliation afterward. Audit-store outages block these new actions or use a bounded durable spool with explicit failure behavior; reads may continue only under a documented policy.

## References

- A2A enterprise authentication/authorization: https://a2a-protocol.org/latest/topics/enterprise-ready/
- Workload identity and mTLS: https://spiffe.io/docs/latest/spire-about/use-cases/
- Prompt-injection defense guidance: https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html

References reviewed 2026-09-11. Product choices and protocol versions must be verified during implementation.
