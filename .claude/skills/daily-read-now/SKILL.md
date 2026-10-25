---
name: daily-read-now
description: Run the DailyRead paper digest on demand for everything since the last report up to now, including papers visible so far today, then publish, email and summarize what came out. Use this whenever the user asks for a paper report now, today's papers, what is new since the last digest, to rerun, refresh or catch up the digest, or mentions DailyRead, the digest page, or new ML / medical-imaging / radiomics / bone papers in this project, even if they do not say "run the pipeline" or name the skill.
---

# DailyRead on demand

The scheduled job runs at 01:00 and reports yesterday. This skill is the manual form: it reports everything
since the last report, including what has become visible so far today, publishes the page(s) to GitHub Pages,
emails the digest to the user's inbox, and tells the user what it found. The pipeline computes its own window
from the last successful run, so there is nothing to work out by hand.

## 1. Preflight (one Bash call)

Work from the project root, the directory that holds `run_daily.sh` (this skill lives under its `.claude/`).

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" && test -x run_daily.sh && ls ~/.daily_read.env >/dev/null && squeue -u "$USER" -n daily_read -h -o "%T %S" 2>/dev/null
```

If the scheduled job shows `RUNNING`, do not start a second run: the two would share the SQLite state, and
`run_daily.sh` refuses with exit code 3 anyway. Tell the user the nightly job is already running and that its
output will arrive by email. `PENDING` is normal and means nothing is running now.

## 2. Run

```bash
./run_daily.sh --include-today
```

Run it in the background: an ordinary day takes 5 to 15 minutes, a multi-day catch-up longer. It is
network-bound and uses a few LLM calls, so it is fine from a login node. Do not read the output file while
waiting; the completion notification arrives on its own. Map what the user asked for onto the flags, and do
not add flags they did not ask for:

| User wants | Add |
|---|---|
| no email this time | `--no-email` |
| nothing published, just local pages | `--no-push` |
| only to see what would be picked, no pages or email | `--dry-run` |
| a specific start date | `--since YYYY-MM-DD` (otherwise the pipeline starts from the last success) |
| an existing day re-rendered after a config change | `./run_daily.sh rebuild --date YYYY-MM-DD --push` instead |

## 3. Read the result

When the run finishes, summarize it with the bundled script, which reads the state database and prints the
latest reports with their counts, URL, publish and email status, headline, curated-journal papers and deep dives:

```bash
python3 .claude/skills/daily-read-now/scripts/report_summary.py --last 3
```

Then pull the operational lines from the newest log for anything the script cannot know:

```bash
grep -E " (WARNING|ERROR) |publish|email sent|finished|IF cut" "$(ls -t logs/run-*.log | head -1)" | cut -c1-200
```

Exit code 3 means another run held the lock; exit code 2 means the env file or venv is missing. A source that
failed is not fatal: the page names it and the next run picks the gap up. "nothing to report" is a real
outcome on a quiet stretch, not an error.

## 4. Tell the user

Lead with the outcome, then one block per day the run produced, newest first:

- date, number of papers, and "+N new" when the run extended a day that already had a page
- the page link
- the headline sentence
- counts by track, and the curated-journal papers by title and venue (these are the ones the user weights most)
- the deep-dive titles
- whether the email went out

Mention once that the nightly run will extend today's page with later arrivals and re-send it with a "+N new"
subject, so running this again later the same day is harmless. Never paste the env file, tokens or API keys;
the logs are already redacted, and nothing in the summary needs them. If the run failed, give the error lines
and the log path, and say what you think the cause is before suggesting a retry.
