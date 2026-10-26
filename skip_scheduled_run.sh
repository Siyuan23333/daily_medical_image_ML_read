#!/bin/bash
# After a manual DailyRead run: retire the scheduled job that is due but has not started, so the day is not reported twice.
# scrontab keeps one recurring job per entry and cancelling it disables the entry, so the schedule is re-armed by
# reinstalling the table; the new instance is then due at the next midnight. A job that is already running is left alone
# (the lock in run_daily.sh keeps it from overlapping, and it would only add later arrivals). Usage: skip_scheduled_run.sh [--all]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ALL="${1:-}"
NOW=$(date +%s)
RUNNING=$(squeue -u "$USER" -n daily_read -h -t RUNNING -o "%i" | head -1 || true)
if [ -n "$RUNNING" ]; then
  echo "scheduled job $RUNNING is running right now; leaving it alone (it will only add papers that arrived after the manual run)"
  exit 0
fi
cancelled=0
while read -r id begin; do
  [ -n "$id" ] || continue
  due=$(date -d "$begin" +%s 2>/dev/null || echo 0)
  if [ "$ALL" = "--all" ] || [ "$due" -le "$NOW" ]; then
    scancel "$id" && echo "cancelled pending scheduled job $id (was due $begin)" && cancelled=$((cancelled + 1))
  else
    echo "pending scheduled job $id is not due until $begin; leaving it"
  fi
done < <(squeue -u "$USER" -n daily_read -h -t PENDING -o "%i %S")
if [ "$cancelled" -gt 0 ]; then
  sleep 2
  "$HERE/install_scrontab.sh" >/dev/null
  echo "schedule re-armed:"
  squeue -u "$USER" -n daily_read -h -o "  job %i due %S (%T)"
else
  echo "nothing cancelled"
fi
