# Dismiss and restore job listings

Members can choose Dismiss job and a reason: Old posting, Already applied elsewhere, Not interested, or No longer available. Dismissed jobs are hidden by default. Enable Show dismissed to see grey listings with reason labels and Restore actions. Dismissal is separate from application status and preserves all submission receipts and saved stages. Source posting dates and first-discovered dates are displayed separately; an employer's original internal date remains unknown unless supplied by that source.

The owner-scoped job_dismissals table survives collection upserts. RLS and member authorization protect mutations, Origin checks prevent CSRF, and all dismiss/restore actions are audited. API application preparation returns 409 until the job is restored. The task-assisted submission bridge checks dismissal on load and intent as well. Dismissal cannot cancel a request already sent to an employer.

Dismissal propagates to the same canonical posting URL after removing common tracking parameters and fragments. Restore removes that matching dismissal. Company/title similarity alone is insufficient to prove duplicate identity, and different aggregator URLs are not automatically linked without shared canonical evidence. Do not claim universal cross-site requisition matching.

Scheduled discovery and application preparation MUST exclude the owner's dismissed jobs, using dismissal_for or the default jobs API filter. Never restore them automatically during a refresh. Email preserves historical outcomes and adds dismissal labels and restoration instructions. Existing submission_unknown states remain blocked regardless of restoration.

Validation: owner-scoped hide/show/restore, persistence across refresh, canonical duplicate handling, origin and role denials, RLS, application-check blocking and preservation of applied stages are covered by integration tests.

The Update status menu includes Successfully applied, Not relevant, Dismissed, Old posting, No longer available and Already applied elsewhere. Marking successfully applied is an explicit user attestation, audited separately from employer confirmation. It preserves earlier uncertain receipt evidence and clears dismissal. Reports label completion confirmed by you.

## Final emailed decisions
Once a job has been emailed, an owner status decision archives and permanently locks it. Archived jobs appear only in Archive, without external links or mutable controls. The API returns 409 on further status, save or preparation requests. Canonical posting identities share the lock; reports exclude archives. Existing finalized emailed decisions are migrated. Non-emailed dismissals remain reversible.
