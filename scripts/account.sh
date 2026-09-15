#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ -f .compose-retired ]]; then
  exec ./JBS/bin/python /home/srimonadi/Enterprise-AI-Hub/scripts/jobsearch_account.py "$@"
fi
exec docker compose -p jobsearch -f compose.yaml exec api python -m scripts.accounts "$@"
