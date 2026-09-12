# Emailed jobs follow-up

The Emailed jobs sidebar page lists the signed-in owner's jobs included in tracked, Gmail-accepted reports, newest email first. Jobs appear once, with their last emailed time. It keeps closed/no-longer-observed jobs available for follow-up and shows dismissed entries by default. Opening this tab clears leftover search/date/workplace filters. Status controls act on the same saved-job, dismissal and application records as Opportunities.

Each report has an external Application link and an Update status in Jobsearch link. The latter opens http://localhost:3105/?view=emailed&job=UUID and requires the user's normal login. It is a read-only navigation link, never a status-changing GET. From the job details, the user can mark successfully applied, dismiss with a reason or restore. Localhost links work on the computer hosting Jobsearch; no public exposure or authentication token is added to email.

The emailed_jobs table stores owner, report hash, job ID, preparation time and Gmail acceptance time. It contains no password, resume or demographics. RLS and explicit owner queries isolate history. Prepared/failed/unconfirmed sends remain absent from the emailed list. Email delivery is protected by the existing durable journal. If Gmail accepts a report but history synchronization fails, repeating the unchanged sender command synchronizes history using its accepted journal entry without resending. SMTP acceptance does not prove inbox arrival.

Tracking begins with this feature. Earlier reports did not store job membership; do not invent historical timestamps or membership. A newly sent current report populates the initial list. Scheduled reports use the same sender and therefore populate the page automatically.
