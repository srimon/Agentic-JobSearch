#!/usr/bin/env bash
set -euo pipefail
if [[ -f /home/srimonadi/Jobsearch/.compose-retired && "${1:-status}" == "status" ]]; then
  exec /home/srimonadi/Jobsearch/JBS/bin/python /home/srimonadi/Enterprise-AI-Hub-consolidation/scripts/jobsearch_operations.py status
fi
case "${1:-status}" in
  up) exec /home/srimonadi/Jobsearch/startupdocker.sh ;;
  stop) exec /home/srimonadi/Jobsearch/stopdocker.sh ;;
  status) exec /home/srimonadi/Jobsearch/JBS/bin/python /home/srimonadi/Jobsearch/scripts/lifecycle.py check --expect "${2:-running}" ;;
  logs) exec tail -n 50 /home/srimonadi/Jobsearch/logs/lifecycle.jsonl ;;
  *) echo 'Usage: scripts/stack.sh {up|stop|status [running|stopped]|logs}' >&2; exit 2 ;;
esac
