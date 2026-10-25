#!/bin/bash
# DailyRead single-command entry point. Usage: ./run_daily.sh [run options]   (see: ./run_daily.sh --help)
set -euo pipefail
# Self-contained environment: scrontab/Slurm jobs do not load ~/.bashrc or modules, so set what we need here.
# Everything below is on the system paths (git, sendmail) or inside the venv, which is built on the system python.
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin${PATH:+:$PATH}"
export LANG="${LANG:-C.UTF-8}" LC_ALL="${LC_ALL:-C.UTF-8}" PYTHONUTF8=1 PYTHONUNBUFFERED=1
: "${HOME:=$(getent passwd "$(id -un)" | cut -d: -f6)}"; export HOME
umask 077
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${DAILY_READ_ENV:-$HOME/.daily_read.env}"
VENV="${DAILY_READ_VENV:-$HOME/envs/daily_read}"
[ -r "$ENV_FILE" ] || { echo "missing $ENV_FILE" >&2; exit 2; }
[ -x "$VENV/bin/python" ] || { echo "missing venv at $VENV (python -m venv $VENV && $VENV/bin/pip install -r $HERE/requirements.txt)" >&2; exit 2; }
cd "$HERE"
mkdir -p logs state digests
# One run at a time: a manual run and the scheduled job must not share the SQLite state concurrently.
exec 9>"$HERE/state/.run.lock"
flock -n 9 || { echo "another DailyRead run is in progress (lock: $HERE/state/.run.lock); try again when it finishes" >&2; exit 3; }
if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then exec "$VENV/bin/python" -m daily_read run --help; fi
case "${1:-}" in rebuild|stats|test-email|test-llm) exec "$VENV/bin/python" -m daily_read "$@";; esac
exec "$VENV/bin/python" -m daily_read run "$@"
