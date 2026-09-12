# Gmail application reporting

Configured September 11, 2026. Sender and sole recipient: sean.chopparapu@gmail.com.

Run in an interactive WSL terminal from /home/srimonadi/Jobsearch:

    ./scripts/email-report.sh preview
    ./scripts/email-report.sh send

The send command prompts for a Google app password using a hidden terminal prompt. Enable Google 2-Step Verification and create an app password at https://myaccount.google.com/apppasswords. Never paste credentials into chat, command arguments, intake, or source files. The credential is held only in the sending process; it is not persisted. Therefore unattended scheduled sending is not enabled.

Transport uses smtp.gmail.com:587 with certificate-validated STARTTLS and SMTP authentication. Sender/recipient are fixed, so job content cannot redirect reports. Reports export only company, title and application status from the active local admin owner's encrypted records. No resume, demographic, contact profile, or raw employer receipt is included.

The CLI reads through the isolated jobsearch API container and JBS Python environment. It does not modify the library stack or mount secrets in the crawler. data/processed/email-delivery.jsonl is an exclusive-lock, fsynced, mode-0600 delivery journal with timestamps, report hashes and outcomes. An intent precedes SMTP submission. Previously accepted or uncertain reports cannot be automatically resent. SMTP acceptance is not proof of inbox arrival. If interrupted after intent, reconcile mailbox delivery before any manual journal remediation. A failed authentication does not send a message.

Verification: four mocked SMTP tests cover TLS, fixed destination, privacy filtering, auth failure, journal permissions, duplicate blocking and ambiguous transport failure. Live preview succeeds. Actual Gmail authentication and delivery remain pending local credential entry.

## Persistent credential update

The user explicitly authorized persistent SMTP credentials. Run `./scripts/email-report.sh configure` from an interactive WSL terminal to enter and confirm the Google app password privately. It writes `/home/srimonadi/Jobsearch/.secrets/gmail_app_password` atomically, with permissions 0600 inside the existing owner-owned 0700 directory. This is a plaintext secret protected by filesystem permissions, not encryption at rest. The `.secrets/` directory is excluded from Git. Do not copy it into source control or ordinary backups. It is not mounted into application containers.

The sender now reads this file when present, validates ownership/type/permissions, and rejects symlink secret files. `./scripts/email-report.sh send` can then run without an interactive password prompt. If no file exists it retains the hidden-prompt fallback. Re-run configure to rotate the credential. No recurring schedule is created by this change. The earlier memory-only limitation is superseded when this optional file is configured.


## Three-hour workflow

An active Codex task named Jobsearch — discover, prepare and report runs every three hours in the existing task. It performs discovery, permitted-source checks, local resume assessment and reporting. Recurring external application submission was rejected by automatic approval review pending narrow employer/destination approval; it is not enabled. Existing unknown submissions stay blocked.

The task writes a non-sensitive run summary to data/processed/scheduled-run-summary.json (jobs, sources, applications, failures lists) and invokes ./scripts/email-report.sh send --scheduled. Email includes application next-action reasons and a three-hour UTC window marker, allowing unchanged status reports in subsequent windows while blocking the same report within one window. This window is a reporting identifier, not the timer's precise start time. Stale/missing summaries are explicitly reported as unverified. No resumes, demographic answers or secrets belong in this summary. Local files, WSL/Docker and the desktop app must be available when the task runs.

Reports now include validated HTTPS job/application links in both plain text and HTML. HTML content is escaped and unsupported URL schemes or embedded credentials are omitted. Aggregator links may lead to the listing rather than directly to an employer form. Unknown submissions include an explicit reconciliation warning.
