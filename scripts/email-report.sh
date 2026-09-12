#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec ./JBS/bin/python scripts/email_report.py "$@"
