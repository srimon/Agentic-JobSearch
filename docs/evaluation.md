# Evaluation and implementation acceptance

Planned checks; none of these is claimed to have passed for Jobsearch.

## Job quality

Create a human-labeled fixture set covering title variants, sales roles mentioning AI, both CDO meanings, remote outside the US, unspecified remote eligibility, multiple locations, conflicting compensation, duplicate requisitions and closed/reopened listings. Measure match precision/recall and country eligibility separately. Set numerical targets only after a baseline is reviewed.

All published derived facts must reference evidence or be unknown. Check first-seen versus posted-date semantics. Verify source failures and incomplete pagination cannot close jobs. Test reversible deduplication and stale-vector suppression.

## Security

- Unlisted authenticated users denied; revoked users lose access according to the documented session policy.
- Ownership checks prevent saved-job/private-note access across users.
- Forged workload/payload identity, expired/wrong-audience tokens and unauthorized A2A task/artifact access denied.
- Delegation cannot expand authority. Peer identity is checked, not merely certificate validity.
- Injection fixtures in user text, HTML, retrieved vectors and A2A artifacts cannot cause unauthorized actions.
- Crawler rejects internal destinations, redirects to them, DNS changes and unsafe artifact/callback URLs.
- Tool gateway rejects unknown tools, invalid arguments, unauthorized records/collections and exhausted budgets.
- Mandatory guardrail/policy/identity outages hold affected work; secrets do not reach output or audit records.
- Audit intent/outcome events are correlated, unsampled and recoverable after interruption.
- Jobsearch identities cannot modify library tables, collections, keys or files.

## Reliability and UI

Test worker crashes, duplicate delivery, lease expiry, outbox restart, indexing failures, partial fetches, source throttling and backup restoration. Verify source links, pagination, filter behavior, review states, keyboard navigation, accessible labels and honest empty/error states.

Use deterministic unit/contract tests for execution rules; integration tests for real service permissions and isolation; a small controlled live-source check for adapters. LLM-as-judge can support quality assessment but cannot replace authorization tests or ground-truth labels. No live tests against library data without separately scoped authorization.
