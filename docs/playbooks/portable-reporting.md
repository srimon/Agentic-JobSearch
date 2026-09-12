# Portable report transport

Implemented 2026-09-12. The sender supports a direct database transport for trusted
report workloads. The live host launcher still defaults to Compose, preserving
the existing production deployment until a controlled reporting cutover.

## Runtime configuration

| Variable | Behavior |
|---|---|
| JOBSEARCH_REPORT_TRANSPORT | `compose` (compatibility default) or `direct`; other values fail closed. |
| JOBSEARCH_DATABASE_URL | Direct mode uses the application's scoped `jobsearch_app` role; owner credentials are rejected. Supply from protected workload configuration. |
| JOBSEARCH_INTAKE_KEY_FILE | Existing application intake key, required to decrypt report payloads. Never replace it during migration. |
| JOBSEARCH_REPORT_STATE_DIR | Persistent directory containing email-delivery.jsonl and scheduled-run-summary.json. Default remains data/processed under project root. |
| JOBSEARCH_REPORT_SECRET_DIR | Owner-only 0700 directory holding owner-only 0600 gmail_app_password. Default remains project .secrets. |
| JOBSEARCH_REPORT_ORIGIN | Origin for status links; HTTPS or loopback HTTP only, without credentials/path/query. Default remains http://localhost:3105. |

Use `python -m scripts.email_report preview` or `send` inside a configured trusted
runtime. The host wrapper now invokes the module from the repository root, so
direct imports work without custom PYTHONPATH settings. `preview` exposes report
content in the terminal; do not use it in CI or logs with real owner data.

Direct mode imports src/applications/reporting.py for owner-scoped export and
report-history writes. It does not require Docker, kubectl, a Docker socket or a
new public HTTP endpoint. The active local admin account remains the report owner;
this is not a multi-tenant report API. Role-name validation is a guard, not proof
of deployment permissions: separately provision and review actual database grants.

## Delivery invariants and deployment limits

The SMTP sender, TLS requirement, recipient, deterministic message ID, body-based
report hash, fsynced journal and flock remain unchanged. Both transports prepare
report membership before SMTP and mark it emailed only after acceptance. Accepted
identical reports reconcile history without resending. Sending/unknown outcomes
remain blocked pending evidence; a database write after SMTP is not atomic with
SMTP acceptance. SMTP credentials and full decrypted records are never passed to
the database transport subprocess or emitted on direct-transport failure.

The journal must be copied from the previous owner after freezing delivery. Use one
sender and storage supporting the required file locks and fsync semantics. Do not
start separate writers with separate journal copies. This change does not provide
distributed exactly-once delivery or authorize automatic retries of unknown sends.
Configure persistent mounts and appropriate file ownership before deploying. A
default root-owned Kubernetes Secret mount may fail the sender's owner/mode checks;
use a reviewed mechanism that provides the required ownership without logging it.

The existing three-hour scheduled-body window/freshness behavior is unchanged.
Changing that or the report origin alters report bodies/hashes and requires a
controlled boundary to avoid duplicate deliveries. The daily scheduler cooldown
discrepancy is a separate open issue. No schedules, production containers, reporting
ownership, recipient or journals were changed during this implementation.

## Validation

`JBS/bin/python -m pytest evaluation -q`: 28 passing tests, including transport
selection, failure redaction, scoped-role rejection, configurable safe links,
private-field filtering and existing delivery/secret/history regressions.

`JBS/bin/python evaluation/run_report_transport_integration.py` creates temporary
network-disconnected PostgreSQL and a report runner sharing only that isolated
network namespace. It mounts only three code files and uses synthetic data and
a temporary key. SMTP is mocked. It verifies real SQL export/history operations,
archive suppression, field filtering, accepted-history reconciliation and
uncertain-send blocking while making Docker execution from the sender fail. It
removes the temporary containers afterward. The harness requires the locally
cached `jobsearch-api:3d48b9b` dependency image and resolves its image ID before use.

Next deployment gate: provision the report worker identity, protected configuration,
persistent journal and egress policy; freeze the old owner before enabling direct
delivery. No production report or email was sent as part of these tests.
