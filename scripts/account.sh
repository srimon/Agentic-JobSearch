#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec docker compose -p jobsearch -f compose.yaml exec api python -m scripts.accounts "$@"
