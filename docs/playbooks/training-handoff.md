# Jobsearch and Training & Preparation

AI Autonomous Job Search is the single job discovery/application workspace at http://localhost:3105/.
It includes all existing sources plus the 55 verified public boards imported from PrepPilot.
Existing intake, ATS/application checks, saved jobs, email reports, immutable archives,
feedback ranking, daily workflow, observability and data tools remain authoritative here.

Training & Preparation is a separate app at http://localhost:3188/. The sidebar opens it.
Active job cards and details include Prepare for this role, passing only the job UUID.
Training resolves current access using the same session; it rejects archived or dismissed jobs.
No resume, answer, password or personal profile is passed in the URL. No automatic application
or state mutation happens when the training link is followed. Archived listings gain no new action.

Training owns interviews, practice feedback, learning controls, resume practice/ATS review,
exams and progress. Jobsearch's application-readiness checks remain here. Model-only training
features remain unavailable while the owner-selected local mode is active.

The Hub runbook docs/runbooks/jobsearch-training.md records release pins and validation.
