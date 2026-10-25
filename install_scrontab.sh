#!/bin/bash
# Render scrontab.txt from scrontab.template using SLURM_ACCOUNT / SLURM_PARTITION from the env file, then install it.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${DAILY_READ_ENV:-$HOME/.daily_read.env}"
[ -r "$ENV_FILE" ] || { echo "missing $ENV_FILE" >&2; exit 2; }
ACCOUNT="$(sed -n 's/^SLURM_ACCOUNT=//p' "$ENV_FILE" | tail -1 | tr -d '"'"'"'"' )"
PARTITION="$(sed -n 's/^SLURM_PARTITION=//p' "$ENV_FILE" | tail -1 | tr -d '"'"'"'"' )"
[ -n "$ACCOUNT" ] || { echo "set SLURM_ACCOUNT=<slurm account> in $ENV_FILE (see: slist)" >&2; exit 2; }
sed -e "s|__SLURM_ACCOUNT__|$ACCOUNT|g" -e "s|__SLURM_PARTITION__|${PARTITION:-a30}|g" -e "s|__ROOT__|$HERE|g" "$HERE/scrontab.template" > "$HERE/scrontab.txt"
scrontab "$HERE/scrontab.txt"
echo "installed:"; scrontab -l
