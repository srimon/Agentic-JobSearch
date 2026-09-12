# Resume intake and application preparation

Implemented 2026-09-11. Open http://localhost:3105, sign in, and choose Resume & profile.

## Resume routing

The default resume is 202609091.pdf. Capital One uses 202609101CAP.pdf, as explicitly confirmed by the user. Preserve the two original versions independently; do not merge their employment histories or alter their dates/titles. Exact normalized Capital One employer names and known corporate-name variants route to capital_one. Recruiter phrases and unknown subsidiaries are not automatically treated as Capital One. The selected filename appears before the source-form handoff. Missing Capital One resumes block preparation rather than silently falling back.

## Intake and privacy

The signed-in member can upload/download/delete PDF, DOCX or UTF-8 TXT resumes up to 5 MiB and store contact details, US work authorization, sponsorship, relocation, workplace preferences, desired base salary, availability and employer exclusions. Unknown answers stay unknown. Profile confirmation is cleared in the browser when a field changes. No passwords, SSN or demographic fields are requested.

Profile, original files, extracted text and saved assessments are AES-256-GCM encrypted with user ID and record type authenticated as associated data. The API alone mounts .secrets/intake_key read-only. Its parent directory must remain 0700. Preserve the key with encrypted database backups; losing it makes saved intake unreadable. Key rotation requires deliberate decrypt/re-encrypt migration and is not automated. The key is not mounted in the collector or frontend.

Private tables have row-level security and explicit user-scoped SQL. Member/administrator access is limited to that authenticated user's records; operator status alone grants no intake access. The collector has no grants on private tables. Runtime code sets the owner context from the session, never from a submitted user ID. This protects against accidental cross-account access, not a compromised database superuser or host administrator.

Mutations require the configured Origin. Actual streamed bytes are bounded, including requests without Content-Length. PDF/DOCX extraction runs in a subprocess with memory/CPU/time limits and concurrency two. Active document containers, oversized archives, malformed files, insufficient text, detected secrets and instruction-like content are rejected. This is not a malware scanner. Files are downloaded as attachments, not rendered by the application. No resume text is sent to an external AI service, Qdrant, crawler, or telemetry. Audit events contain owner IDs, actions and status, not resume/contact contents.

Deletion removes the current profile/resumes/checks in the live database; audit events and preexisting backups are not erased. The app remains localhost-only, using its existing local authentication. Internet-facing HTTPS/WAF/MFA hardening is not part of this change.

## Evidence checks and application state

Open a current matching US opportunity and choose Check resume & prepare application. The deterministic check compares a fixed set of data/AI topics and shows excerpts from the stored job description and selected resume. A mention is not proof of proficiency. Explicit requirement sentences are listed for verification; years, degrees, employment facts and screening answers are not inferred. The check is not an employer ATS score, an automatic eligibility decision, or a hiring prediction. Summary-only sources are flagged as incomplete. Scanned PDFs and DOCX headers/layout may require manual review of extraction.

Checks are encrypted and deduplicated per owner/job ID. Profile, resume and job content versions make earlier checks stale after changes. Existing content quarantine, US eligibility and current-match gates remain enforced. Exact employer exclusions block preparation. Other preferences are stored for future submission policy; this version does not use them to autonomously approve or reject jobs.

Current states are needs_information, needs_site_access and content_review. No state claims submitted. Opening a source/employer form or downloading a resume is not submission. This release has no automated external sender or bulk apply scheduler. Saved-job stage labels elsewhere in the app are manual user tracking, not verified submission receipts.

The user has requested applications with the appropriate resume. Actual submissions remain pending completed intake answers and verified per-site access. No new blanket confirmation is needed solely to restate that authorization. Unknown screening answers or site-specific declarations require the user's answer; do not invent or bypass them. Never collect job-board passwords/cookies in the intake form. Future senders need destination validation, exact answer mapping, durable intent and receipt storage, duplicate prevention, and reconciliation of unknown outcomes before retries.

Public listing access is not submission access:
- Greenhouse's Job Board POST endpoint requires Basic authentication: https://docs.greenhouse.io/job-board.html
- Lever submission requires an API key generated by an account Super Admin: https://github.com/lever/postings-api#apply-to-a-job-posting
- Ashby applicationForm.submit uses employer-managed API credentials: https://developers.ashbyhq.com/reference/authentication

For unavailable submission access, the UI provides the original employer/source form and the selected resume download. Aggregator links can require a further employer-site step. These links are not claimed as automated integrations.

## Verification

16 intake/authentication/collection integration tests passed in jobsearch_auth_test; 51 collection/source/observability tests passed separately. Tests cover encryption binding, cross-account reads, RLS, worker denial, CSRF, upload bounds, malformed documents, routing, stale checks and no fabricated submission state. Production frontend build passed; a headless browser test with synthetic API responses verified navigation, two resume uploads, save feedback and application-check navigation. Live authenticated API checks verified both imported resumes and created three Capital One checks using the Capital One PDF. No external application was submitted. All twelve Jobsearch services were healthy and lifecycle reported the library containers unchanged.


## Optional self-identification update

The user explicitly authorized encrypted storage of voluntarily supplied demographic answers. Intake now supports race/ethnicity, gender/sex, protected veteran status and disability status. Blank/not_provided is distinct from no and prefer_not_to_disclose. No values are inferred from names, resumes or job text. Race/ethnicity and gender/sex accept the user's own wording; source-specific choices must not be silently coerced. The use_for_applications preference starts false and the UI clears it whenever an answer changes. Submission automation must check this preference and exact question meaning before using answers; an unanswered or incompatible question needs user input. These attributes must never be used for job relevance, ATS scoring or included in email reports. There is no automatic sender yet.

Demographics are inside the existing encrypted, owner-scoped profile payload. No database columns containing plaintext demographic answers were added. Logs and audits record the profile update event only. The intake rejects unknown password/SSN fields and formatted SSNs in text; this is not a guarantee of detecting every possible secret entered into free text. Do not place site credentials or SSNs in the profile or resume.

LinkedIn links are extracted only from explicit linkedin.com/in/ text in the uploaded resumes, without network lookup. If there is exactly one unique candidate and the saved field is empty, the browser prefills it as an unsaved suggestion and clears profile confirmation. Multiple candidates do not auto-select a URL; a manually saved value is preserved. The user reviews and saves the profile. Both current resume variants yielded the same URL. No employer or demographic facts are derived from that URL.

Validation for this update: 18 integration tests passed (including authentication regressions, demographic encryption and cross-account isolation), plus two LinkedIn extraction tests. The API/frontend production build passed. Resume originals and chromadb files were not modified.


## Additional optional fields

Pronouns, gender identity and sexual orientation are separate optional fields within the encrypted demographics payload. They accept explicit user wording or Prefer not to disclose, default to blank, and are never inferred. Gender identity does not overwrite gender/sex. Editing any of these clears disclosure permission and profile confirmation in the UI. Existing saved profiles load with blank defaults without rewriting stored answers. The existing owner-only access, no-content audit logging and exclusion from matching/reporting apply.
