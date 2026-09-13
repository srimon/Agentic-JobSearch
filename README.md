> Current production (2026-09-13): Jobsearch runs in enterprise-hub/jbs-production at http://localhost:3105 with one worker and scheduler. Old Compose application containers are stopped and fenced by .compose-retired. Do not run raw Compose up or reactivate them. Use the Hub runbook under /home/srimonadi/Enterprise-AI-Hub-consolidation/docs/runbooks/enterprise-ai-hub.md. Existing account.sh and email-report.sh route to the active runtime. Daily workflow: 08:00 America/Los_Angeles. MBK migration and old-infrastructure cleanup remain separate pending work.

# JBS — AI Autonomous Job Search

A private React/Next.js application for discovering US data and AI leadership opportunities, reviewing resume evidence, tracking application decisions, and learning bounded ranking preferences from explicit feedback.

## Implemented

- FastAPI backend and React/Next.js frontend, with local account authentication.
- Isolated PostgreSQL, Qdrant and Redis services; a deterministic source collector and durable refresh queue.
- Supported public ATS feeds, Dice, Jobicy and Remotive adapters. Coverage is bounded, not the entire internet.
- Past-24-hours default on active listing screens, with wider date filters available.
- Encrypted owner-scoped intake and resumes, deterministic resume evidence checks, and separate Capital One resume routing.
- Emailed-job follow-up, immutable archive decisions and duplicate-attempt protections. Uncertain submissions require reconciliation.
- Explainable feedback ranking with thresholds, bounded adjustments, version history and pause/reset/restore controls.
- Gmail reporting with delivery deduplication; source diagnostics and observability services.
- Responsive visuals, explanatory illustrations and progress animations with reduced-motion support.

## Automation boundaries

The local collector schedules source refreshes. A separately configured Codex automation performs discovery, local preparation and email reporting every three hours. That desktop automation is not installed merely by cloning this repository. Scheduled runs do not submit applications or upload resumes to employers. Learning changes ranking only, never eligibility, privacy, archive locks or application authority. The full secured multiagent/A2A architecture described in design documents is not yet implemented.

> Collector deployment: a separate scheduler and one leased worker are active. Lifecycle commands include both Compose files. See [worker operations and cutover](docs/playbooks/worker-leases.md); direct base-only Compose commands omit the scheduler.

## Local deployment

Requires WSL/Linux, Docker Compose, Python 3.12 and Node.js 22 for frontend development. Use a project-local Python environment named `JBS`:

```sh
python3 -m venv JBS
JBS/bin/pip install -r requirements.txt
cd frontend
npm ci
cd ..
```

Read [deployment](docs/deployment.md), [isolated stack decision](docs/decisions/0002-isolated-stack.md), [local authentication](docs/playbooks/local-authentication.md) and [operations](docs/playbooks/operations.md) before starting a new installation. Runtime credentials, secret configuration files and database migrations must be provisioned for the new environment; they are intentionally not committed. Some lifecycle paths target the original WSL host and must be reviewed for a different installation.

For an already configured local deployment:

```sh
./scripts/stack.sh up
./scripts/stack.sh status
./scripts/stack.sh stop
```

The web interface is at http://localhost:3105. Never point this application's services at another application's database or volumes.

## Validation

```sh
JBS/bin/python -m unittest evaluation.test_learning evaluation.test_email_report evaluation.test_email_secret evaluation.test_scheduled_email evaluation.test_email_tracking
cd frontend && npm run build
```

Database integration tests require a separately provisioned disposable test database. Never run test schema resets against application data.

## Data and credentials

Git excludes `.secrets`, environment files (except the example), resumes, runtime data, logs, work files, databases, Python environments and generated frontend files. Back up encrypted application data and its encryption key separately using an appropriate secure backup process. A source-code clone does not contain your profile, application history, email credentials or database contents.

## Design and operating guides

- [Enterprise AI Hub inventory and Kubernetes migration plan](docs/kubernetes-migration-plan.md)

- [Architecture](docs/architecture.md) and [AI context](ai.md)
- [Feedback learning](docs/playbooks/feedback-learning.md)
- [Collection](docs/playbooks/collection.md) and [source integrations](docs/playbooks/job-board-integrations.md)
- [Intake](docs/playbooks/resume-intake.md), [email reporting](docs/playbooks/email-reporting.md), and [archive decisions](docs/playbooks/job-dismissal.md)

Design documents include historical decisions; later implementation notes and ADRs supersede earlier plans.
