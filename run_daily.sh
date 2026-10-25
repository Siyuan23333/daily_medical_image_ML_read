#!/bin/bash
# DailyRead single-command entry point. Usage: ./run_daily.sh [run options]   (see: ./run_daily.sh --help)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${DAILY_READ_ENV:-$HOME/.daily_read.env}"
VENV="${DAILY_READ_VENV:-$HOME/envs/daily_read}"
[ -r "$ENV_FILE" ] || { echo "missing $ENV_FILE" >&2; exit 2; }
[ -x "$VENV/bin/python" ] || { echo "missing venv at $VENV (python -m venv $VENV && $VENV/bin/pip install -r $HERE/requirements.txt)" >&2; exit 2; }
cd "$HERE"
mkdir -p logs state digests
if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then exec "$VENV/bin/python" -m daily_read run --help; fi
case "${1:-}" in rebuild|stats|test-email|test-llm) exec "$VENV/bin/python" -m daily_read "$@";; esac
exec "$VENV/bin/python" -m daily_read run "$@"
