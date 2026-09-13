#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ -f .compose-retired ]]; then
  exec ./JBS/bin/python /home/srimonadi/Enterprise-AI-Hub-consolidation/scripts/jobsearch_report.py "$@"
fi
exec ./JBS/bin/python -m scripts.email_report "$@"
