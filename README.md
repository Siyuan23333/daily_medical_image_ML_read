# DailyRead

Daily digest of new papers in machine learning for medical imaging, radiomics and bone research.
Collects from arXiv, medRxiv/bioRxiv, PubMed, Crossref and the Springer Nature API, filters for
relevance with DeepSeek, writes summaries, publishes an HTML page per day to GitHub Pages, and emails a link.

See `SPEC.md` for the full specification and decisions log.

## One-time setup

```bash
python3 -m venv ~/envs/daily_read && ~/envs/daily_read/bin/pip install -r requirements.txt
chmod 600 ~/.daily_read.env     # DEEPSEEK_API_KEY, GITHUB_TOKEN, GITHUB_REPO, SPRINGER_*_API_KEY, ELSEVIER_API_KEY,
                                # CONTACT_EMAIL, DIGEST_EMAIL_TO, DIGEST_EMAIL_FROM, SLURM_ACCOUNT, SLURM_PARTITION
./run_daily.sh test-llm         # one small DeepSeek call
./run_daily.sh test-email       # one test email through the Purdue relay
./install_scrontab.sh           # render scrontab.txt from scrontab.template and install the daily 00:00 standby job (Gilbreth)
```

## Daily use

```bash
./run_daily.sh                              # the daily run (what scrontab calls)
./run_daily.sh --dry-run                    # collect + score only, print score distribution
./run_daily.sh --no-llm                     # collect + prefilter only, list candidates
./run_daily.sh --no-email --no-push         # full run but keep everything local
./run_daily.sh --since 2026-10-20           # one report per day from that date (catch-up)
./run_daily.sh --include-today              # manual run: everything since the last report, including today so far
./run_daily.sh rebuild --date 2026-10-24    # re-render one day's page from stored results
./run_daily.sh stats                        # score distribution and recent scored papers
```

`run_daily.sh` sets its own PATH, locale and HOME and references the venv and env file by absolute path, so it
runs the same under scrontab (which ignores your shell environment and never loads `~/.bashrc`) as from a terminal.

In Claude Code, `/daily-read-now` (project skill in `.claude/skills/daily-read-now/`) runs the manual form and summarizes the result.
To use it from any directory, install a personal copy with the project path filled in:

```bash
mkdir -p ~/.claude/skills && rm -rf ~/.claude/skills/daily-read-now && cp -r .claude/skills/daily-read-now ~/.claude/skills/ \
  && sed -i "s|__PROJECT_ROOT__|$PWD|g" ~/.claude/skills/daily-read-now/SKILL.md
```
A day's page can grow: if a later run finds more papers for a day that already has a report, the page is regenerated with
the additions and re-sent with a "+N new" subject. Only one run can hold `state/.run.lock` at a time.

Reports: `digests/YYYY-MM-DD.html` and `.md`, plus `digests/index.html`. State: `state/daily_read.sqlite`
(backed up to `~/daily_read_state/`). Logs: `logs/`.

## Layout

```
config/     settings.yaml journals.yaml pubmed_queries.yaml keywords.yaml scope.md
prompts/    score.md summary.md deepdive.md headline.md
daily_read/ sources/ fulltext/ pipeline.py llm.py render.py publish.py mail.py state.py cli.py
templates/  day.html.j2 index.html.j2 day.md.j2 email.txt.j2 email.html.j2
```

Edit `config/scope.md` to change what counts as relevant, `config/settings.yaml` for thresholds, top-N, email and schedule parameters.
Thresholds are per source class (`relevance.thresholds`: `curated` journals 7, `pubmed_query` 9, `preprint` 10) and journal
papers below `relevance.min_impact_factor` (2) are dropped; preprints and venues with no known impact factor are kept.
A PubMed query in `config/pubmed_queries.yaml` may set its own `threshold` (the HR-pQCT/DXA query uses 8).
After changing any of these, `./run_daily.sh rebuild --date YYYY-MM-DD` re-renders an existing day under the new rules.
