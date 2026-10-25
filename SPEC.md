# DailyRead: daily digest of new ML + medical papers

Specification v1.0, 2026-10-25. Status: agreed, ready to build.

## 1. Goal

A reusable pipeline that, once a day and with a single command, collects the
academic papers published in the previous day in the user's field, filters them
for relevance, summarizes them with an LLM, publishes an HTML digest page, and
emails the user a link plus a short summary.

Field: machine learning on medical data, imaging-centered, with special
interest in radiomics and bone/skeletal research.

Non-goals for v1: full-text access to paywalled papers beyond the routes in
section 5, a search interface over past digests, multi-user support.

## 2. Relevance scope

The LLM scores each candidate against this scope text (kept in
`config/scope.md` so it can be edited without touching code).

Core (always relevant):
- Machine learning, deep learning, or foundation models applied to medical
  images: CT, MRI, X-ray, DXA, ultrasound, PET/SPECT, digital pathology,
  ophthalmic and dermatologic imaging.
- Radiomics in any organ system or modality, including feature extraction,
  harmonization, reproducibility, and radiomics-based prediction models.
- Bone and skeletal topics with any computational or quantitative-imaging
  method: osteoporosis, fracture risk and detection, bone mineral density,
  DXA, HR-pQCT, bone age, skeletal segmentation, osteoarthritis imaging, bone
  tumours, orthopaedic imaging.

Included (relevant when the paper is clearly about ML on clinical data):
- EHR-based prediction and phenotyping.
- Clinical NLP and clinical LLM evaluation.
- Multimodal models combining imaging with clinical, text, or omics data.

Excluded:
- Drug discovery, protein structure, molecular or cell-level ML without a
  clinical data component.
- Pure ML methods papers with no medical data.
- Non-ML clinical papers from the journal list (bone journals included):
  trials, epidemiology, mechanistic biology without computational methods.
- Editorials, errata, corrections, news items. Reviews and surveys are kept
  but tagged `review`.

Scoring: integer 0 to 10. The minimum score depends on where the paper came
from (decided 2026-10-25 after the trial run):

| Source class | Minimum score | Why |
|---|---|---|
| `curated` (the journal list in section 4) | 7 | high-trust venues; a looser bar admits the borderline EHR/NLP and human-AI papers |
| `pubmed_query` (PubMed topic queries) | 9 | the score-8 hits were mostly dental, orthopaedic and sports-medicine venues |
| `preprint` (arXiv, medRxiv, bioRxiv) | 9 | volume control; score 8 preprints were on-topic but numerous |

After scoring, journal papers whose venue impact factor is below 2 are dropped
(`min_impact_factor`). The value is the JCR figure for the curated list and the
OpenAlex two-year mean citedness elsewhere; preprints and venues with no known
value are kept. On the trial days this removed only JoVE (0.6) and Oncology (1.8).
A single `--threshold N` flag overrides all three classes for trial runs.

The top 5 by score (tie-break: core track before included track, then journal
tier) receive the full-text deep dive. All of these numbers live in
`config/settings.yaml` under `relevance`.

Tracks used for grouping in the digest: `imaging-ml`, `radiomics`, `bone`,
`ehr-nlp`. A paper gets one primary track.

## 3. Sources

"Published in the last day" means first appeared in a source between the end of
the previous successful run and now. Preprint servers and the Springer API are
same-day. PubMed-only journals arrive 1 to 3 days after online publication;
the digest labels those entries with their actual publication date.

### 3.1 Preprint servers (same-day, full text always available)

| Source | Access | Query |
|---|---|---|
| arXiv | `export.arxiv.org/api/query`, no key, 1 request per 3 s | categories cs.CV, cs.LG, cs.AI, cs.CL, eess.IV, stat.ML, q-bio.QM; `submittedDate` window; medical-keyword prefilter |
| medRxiv, bioRxiv | `api.biorxiv.org/details/{server}/{from}/{to}/{cursor}`, no key | all categories; keyword prefilter |

### 3.2 Topic queries across all of PubMed (catches papers in unlisted journals)

PubMed E-utilities `esearch` with `datetype=edat`, then `efetch` for abstracts.
Three standing queries:

| Key | Covers | Minimum score |
|---|---|---|
| `radiomics` | radiomics anywhere | 9 (class default) |
| `bone_ml` | bone or skeletal terms AND ML terms | 9 (class default) |
| `hrpqct_dxa` | HR-pQCT, pQCT or trabecular bone score anywhere; DXA in a bone context; no ML required (added 2026-10-25, about 6 papers a day) | 8 (per-query `threshold`) |

A query may carry its own `threshold`; a paper matched by several queries takes
the lowest. (A fourth query, medical imaging AND deep learning, was dropped on
2026-10-25 because it pulled in about 15 papers a day from unlisted journals
while arXiv and the curated imaging journals already cover imaging ML.) Exact
query strings live in `config/pubmed_queries.yaml`. Optional `NCBI_API_KEY`
raises the rate limit from 3 to 10 requests per second.

The scope and scoring prompt treat bone studies whose central method is
HR-pQCT, pQCT, DXA or TBS as core even without machine learning (8-9), and
medRxiv/bioRxiv preprints with those terms skip the ML-term prefilter.

### 3.3 Curated journal list (17 venues)

Every paper from these journals is a candidate and goes through the same
relevance filter as everything else.

| Journal | ISSN | Publisher | New-paper detection | Abstract source |
|---|---|---|---|---|
| Nature Medicine | 1546-170X | Springer Nature (id 41591) | Springer Metadata API | Springer API, same day |
| Nature Machine Intelligence | 2522-5839 | Springer Nature (id 42256) | Springer Metadata API | Springer API, same day |
| Nature Biomedical Engineering | 2157-846X | Springer Nature (id 41551) | Springer Metadata API | Springer API, same day |
| npj Digital Medicine | 2398-6352 | Springer Nature (id 41746), OA | Springer Metadata API | Springer API, same day |
| The Lancet Digital Health | 2589-7500 | Elsevier, OA | Crossref | PubMed (1-3 d) |
| JAMIA | 1527-974X | Oxford University Press | Crossref | PubMed (1-3 d) |
| JAMA Network Open | 2574-3805 | AMA, OA | Crossref | PubMed (1-3 d) |
| Cell Reports Medicine | 2666-3791 | Elsevier/Cell Press, OA | Crossref | PubMed (1-3 d) |
| Radiology | 1527-1315 | RSNA | Crossref | PubMed (1-3 d) |
| Radiology: Artificial Intelligence | 2638-6100 | RSNA | Crossref | PubMed (1-3 d) |
| IEEE Transactions on Medical Imaging | 1558-254X | IEEE | Crossref | PubMed (1-3 d) |
| Medical Image Analysis | 1361-8415 (print ISSN; 1361-8423 fails on Crossref) | Elsevier | Crossref | PubMed (1-3 d) |
| European Radiology | 1432-1084 | Springer (id 330) | Springer Metadata API | Springer API, same day |
| JBMR | 1523-4681 (print 0884-0431) | Oxford University Press | Crossref | PubMed (1-3 d) |
| JBMR Plus | 2473-4039 | Oxford University Press, OA | Crossref | PubMed (1-3 d) |
| Bone Research | 2095-6231 (print 2095-4700; PubMed name "Bone Res") | Springer Nature (id 41413), OA | Springer Metadata API | Springer API, same day |
| Bone | 8756-3282 | Elsevier | Crossref | PubMed (1-3 d) |

All six Springer journal ids were verified against the Metadata API on
2026-10-25.

Crossref and PubMed entries for the same DOI are merged. A Crossref-detected
paper whose abstract has not reached PubMed yet is held (not shown) for up to
5 days, then shown title-only with a note.

## 4. Pipeline stages

1. **Collect**: query every source for the window `[last_success - 12 h, now]`.
   The 12-hour overlap plus deduplication tolerates clock and indexing jitter.
2. **Normalize and deduplicate**: build one record per paper keyed by DOI,
   else arXiv id, else PMID, else normalized-title hash. Merge preprint and
   journal versions when DOI or title+first-author match. Skip anything
   already in the state database.
3. **Prefilter**: keyword regex lists (`config/keywords.yaml`) drop obvious
   non-matches cheaply. Journal-list papers always pass the prefilter.
4. **Score**: DeepSeek reads title, abstract, venue and returns JSON
   `{score, track, is_review, reason}`. Batched 10 papers per call.
5. **Fetch full text** for the top-N (section 5).
6. **Summarize**: abstract-based summary for every included paper; deep dive
   for top-N.
7. **Render**: HTML page and Markdown twin for the day; regenerate
   `index.html`.
8. **Publish**: commit and push the pages to GitHub; verify the Pages URL
   returns 200 (retry for up to 10 minutes, Pages builds are asynchronous).
9. **Email**: send summary with link.
10. **Record**: mark papers as seen, store scores and summaries, write
    `last_success` timestamp. Steps 1 to 9 failing partway must not advance
    `last_success`.

## 5. Full-text retrieval order

Applied only to top-N papers, in this order; the first hit wins.

1. **Open-access copy**: Unpaywall (`best_oa_location`), Europe PMC full-text
   XML when a PMCID exists, Springer Open Access API (JATS) for Springer
   Nature OA papers.
2. **Preprint**: arXiv or medRxiv/bioRxiv match by title similarity (>= 0.9
   token Jaccard) plus first-author surname.
3. **Publisher API key**: Elsevier Article Retrieval API (Medical Image
   Analysis, Bone, and OA Elsevier titles) once the TDM key is approved;
   Springer OA API is already covered by step 1.
4. **Abstract only**: deep dive is written from the abstract and labeled as
   such.

PDFs are converted with PyMuPDF; JATS/XML bodies are flattened to text.
Input to the LLM is capped at 25k tokens (introduction, methods, results,
discussion preferred over references and supplements).

Explicitly not used: EZproxy/OpenAthens sessions, personal publisher logins,
scraping of ScienceDirect, Nature, IEEE Xplore, Oxford Academic or RSNA pages.

## 6. Summarization

LLM: DeepSeek via the OpenAI-compatible endpoint `https://api.deepseek.com`.
Model `deepseek-chat` for scoring and summaries; `deepseek-reasoner` optional
for deep dives (setting). Temperature 0.2. All prompts in `prompts/`.

Abstract summary (every included paper), 3 to 5 sentences:
problem, data (modality, cohort size, source), method, main quantitative
result, why it matters. No hype words.

Deep dive (top-N), 150 to 300 words plus bullets: datasets and sizes,
model/method details, validation design (internal, external, prospective),
main metrics with numbers, limitations, code and data availability.

A daily headline paragraph (3 to 4 sentences) summarizes the day across
tracks for the email body and the top of the page.

Estimated cost: well under USD 0.20 per day at current DeepSeek pricing
(roughly 0.3 million tokens per day).

## 7. Outputs

Venue impact factor: curated-list journals use the Journal Impact Factor from
`config/impact_factors.yaml` (JCR values, year noted). Any other journal is
looked up once in OpenAlex by ISSN and its 2-year mean citedness is shown as
an approximate impact factor, cached in the state database. Preprints show
no impact factor.

### 7.1 HTML page (GitHub Pages)

- One page per day: `YYYY-MM-DD.html`; `index.html` lists all days newest
  first with paper counts per track.
- Page layout: headline paragraph; counts per track; a contents table listing
  every paper's title and venue grouped by track, each title linking to its
  summary; "Deep dives" section; then one section per track. Each paper shows title, first three authors,
  venue with its impact factor, publication date, score badge, links (DOI, PDF or arXiv, PubMed),
  the abstract summary, and a collapsible deep dive when present.
- Single self-contained HTML file per day (inline CSS, no external
  dependencies), readable on a phone, light and dark theme.
- A Markdown twin `digests/YYYY-MM-DD.md` is kept in the repo for grep and
  for use as LLM context later.
- URL pattern: `https://<owner>.github.io/<repo>/YYYY-MM-DD.html`.

### 7.2 Email

- To and from the addresses in `DIGEST_EMAIL_TO` and `DIGEST_EMAIL_FROM` (the
  user's Purdue inbox), sent with the node's
  local `sendmail`, which relays through `smtp.purdue.edu`. No credentials.
  The Gmail test bounced at the relay, so no mail goes to Gmail.
- Subject: `[DailyRead] 2026-10-25: 14 papers (bone 3, radiomics 5, imaging 4, ehr-nlp 2)`.
- Body (plain text plus HTML alternative): page link, headline paragraph,
  one line per deep-dive paper (title, venue, one-sentence takeaway), link
  again. Nothing else.
- One email per report. A catch-up run that generates several daily reports
  sends one email per day, oldest first.
- On pipeline failure a short error email is sent with the log tail.

## 8. Scheduling

Slurm `scrontab` on Gilbreth (user crontab is disabled by PAM).

```
#SCRON --account=__SLURM_ACCOUNT__ --partition=__SLURM_PARTITION__ --qos=standby
#SCRON --gpus-per-node=1 --nodes=1 --ntasks=1 --cpus-per-task=2 --mem=8G
#SCRON --time=02:00:00 --job-name=daily_read
#SCRON --output=__ROOT__/logs/scron-%j.log
0 1 * * * __ROOT__/run_daily.sh
```

- `install_scrontab.sh` renders the placeholders from `SLURM_ACCOUNT`, `SLURM_PARTITION` and the project path.
- Submitted at 01:00 America/New_York on standby (not charged); moved from 04:00 on 2026-10-25 to give a queued standby job more of the night.
- No `--deadline`: scrontab evaluates `now+...` when the table is installed,
  which Slurm rejects against the scheduled start. A standby job that waits
  simply runs later; scrontab keeps one job per entry, so runs never overlap.
  Measured on go-live day, standby start estimates were 2 to 7 days out on
  every GPU partition while `normal` QOS started on time; switching is the
  one-word change `--qos=normal` in `scrontab.txt`.
- `--gpus-per-node=1` is required only because Gilbreth partitions are GPU
  partitions; the pipeline uses no GPU. During the build, test whether a
  GPU-less request is accepted, which would improve standby availability.
- Verified 2026-10-25: compute nodes have outbound HTTPS to all sources and
  can reach the Purdue mail relay.

Manual run (single command, same code path):

```
./run_daily.sh                 # normal daily run
./run_daily.sh --dry-run       # collect and score, no LLM summaries, no publish, no email
./run_daily.sh --no-email --no-push
./run_daily.sh --since 2026-10-20   # one report per day from that date; still deduplicates
./run_daily.sh --date 2026-10-24    # regenerate one day's page from stored results
```

`run_daily.sh` loads `~/.daily_read.env`, activates the Python environment,
runs `python -m daily_read run "$@"`, and exits non-zero on failure.

## 9. Catch-up and missed runs: one report per calendar day

Reports are always per calendar day (America/New_York), never per run.

- Every paper gets a **digest date** = the day it became visible in its
  source (arXiv announcement date, Springer `onlineDate`, Crossref created
  date, PubMed entry date, bioRxiv/medRxiv posting date), converted to
  Eastern time.
- A normal run covers the window `[last_success - 12 h, now]`, groups new
  papers by digest date, and produces one report per date that has at least
  one new paper. On an ordinary morning that is one report, for yesterday.
- Manual runs (`--include-today`, wrapped by the `/daily-read-now` Claude Code
  skill) report everything since the last report including papers visible so
  far today. The next run extends that day's page with later arrivals and
  re-sends it with a "+N new" subject; a page for a day is therefore never
  replaced by a smaller one. A lock file keeps manual and scheduled runs from
  overlapping.
- If a run is skipped or delayed (standby queue, outage, travel), the next run's
  window extends back to the last success, capped at 7 days, and produces
  one report per missed day, each containing only that day's papers, each
  with its own page, Markdown twin, and email. Emails are sent oldest day
  first. Seven missed days give seven reports.
- Late arrivals: if a paper's digest date already has a published report
  (typical for PubMed-lagged journal papers), the paper goes into the report
  for the current day and is tagged `late (published YYYY-MM-DD)`. Published
  reports are never rewritten automatically.
- A day with zero relevant papers still gets a short report ("no new
  relevant papers") so the index has no silent gaps.
- If the gap exceeds 7 days, the run generates the most recent 7 days and
  the oldest of them notes the truncation. `./run_daily.sh --since DATE`
  rebuilds older days on demand, in 7-day slices.
- Per-source failure does not abort the run; each affected report lists the
  failed sources. A run with zero sources succeeding aborts, emails the
  error, and does not advance `last_success`.

## 10. State and storage

- Code: the project directory on Gilbreth scratch (git repo, pushed to
  GitHub, so the code is durable even though scratch is purged after 60 days
  of inactivity; daily runs also keep the files active).
- State: SQLite `state/daily_read.sqlite` with tables `papers` (ids, title,
  venue, dates, source, score, track, summaries, full-text status, digest
  date) and `runs` (start, end, window, counts, status). Copied to
  `$HOME/daily_read_state/` after each successful run as a backup.
- Logs: `logs/`, rotated after 90 days.
- Published pages and Markdown digests live in the GitHub repo
  (`gh-pages` branch), which is the durable archive.

## 11. Configuration and secrets

`~/.daily_read.env`, permissions 600, never committed, never printed:

```
DEEPSEEK_API_KEY=            # required (to be added)
GITHUB_TOKEN=                # required, fine-grained PAT, Contents read/write on the repo (to be added)
GITHUB_REPO=owner/daily-read # required (to be added)
SPRINGER_METADATA_API_KEY=   # present, verified
SPRINGER_OPEN_ACCESS_API_KEY=# present, verified
ELSEVIER_API_KEY=            # present; article retrieval pending Elsevier TDM review
ELSEVIER_INSTTOKEN=          # optional, if Purdue Libraries issues one
NCBI_API_KEY=                # optional
CONTACT_EMAIL=...         # polite-pool address for Unpaywall, Crossref, OpenAlex, NCBI; joins the User-Agent
DIGEST_EMAIL_TO=...       # digest recipients, comma-separated
DIGEST_EMAIL_FROM=...     # sender address accepted by the Purdue relay
SLURM_ACCOUNT=...         # for install_scrontab.sh
SLURM_PARTITION=a30       # for install_scrontab.sh
```

Non-secret settings in `config/settings.yaml`: run time zone, per-source score thresholds, minimum impact factor,
top-N, lookback caps, email addresses, journal list, Springer journal ids,
PubMed queries, keyword lists, model names.

## 12. Repository layout

```
daily_read/
  SPEC.md
  README.md
  run_daily.sh
  scrontab.txt              # the #SCRON block to install with `scrontab -e`
  environment.yml           # conda env spec (module conda/2025.09)
  config/  settings.yaml  journals.yaml  pubmed_queries.yaml  keywords.yaml  scope.md
  prompts/ score.md  summary.md  deepdive.md  headline.md
  daily_read/               # Python package
    sources/  arxiv.py  biorxiv.py  pubmed.py  crossref.py  springer.py
    fulltext/ unpaywall.py  europepmc.py  preprint_match.py  elsevier.py  pdf.py
    llm.py  dedup.py  render.py  publish.py  mail.py  state.py  cli.py
  templates/ day.html.j2  index.html.j2  email.txt.j2  email.html.j2
  tests/
  state/   logs/   digests/   (git-ignored except digests)
```

Python 3.11+ via the `conda` module; dependencies: requests, feedparser,
pymupdf, jinja2, pyyaml, openai (client for DeepSeek), rapidfuzz, pytest.

## 13. Acceptance criteria

1. `./run_daily.sh --dry-run` on a login node completes in under 15 minutes,
   lists candidates per source, and shows scores without calling the
   summarizer or sending anything.
2. A full run produces a page at the Pages URL, a Markdown twin, a state
   update, and one email, and a second immediate run reports zero new papers.
3. Killing a source (bad key, network block) still yields a page that names
   the failed source.
4. The scrontab job runs unattended for 5 consecutive days; any delayed day
   is covered by the catch-up window.
5. No secret value appears in logs, pages, emails, or the repo.

## 14. Decisions log

| Date | Decision |
|---|---|
| 2026-10-25 | Sources: arXiv, PubMed, medRxiv/bioRxiv, 17 curated journals |
| 2026-10-25 | Topic-filter all journals, including bone journals |
| 2026-10-25 | Full-text order: OA, preprint, publisher API, abstract only |
| 2026-10-25 | No personal publisher logins or proxy scraping |
| 2026-10-25 | Summarizer: DeepSeek API |
| 2026-10-25 | Depth: abstract summaries for all, deep dive for top 5 |
| 2026-10-25 | Delivery: HTML on GitHub Pages (new public repo) + email with link and summary |
| 2026-10-25 | Email: to Gmail, from the Purdue address via the Purdue relay |
| 2026-10-25 | Email recipient changed to the Purdue inbox after the Gmail test bounced; no more mail to Gmail |
| 2026-10-25 | Scheduler: scrontab, standby QOS, 04:00 Eastern, 2 h time limit, no --deadline (incompatible with scrontab's scheduled start; Slurm rejects the pair) |
| 2026-10-25 | Scope: imaging-centered; ML/DL/foundation models, radiomics, bone core; EHR and NLP included |
| 2026-10-25 | Top-5 deep dives confirmed; score threshold to be set after a DeepSeek trial run |
| 2026-10-25 | Missed days produce one report per calendar day, not one merged report |
| 2026-10-25 | Threshold = 8 after trial; page gets a contents table (title + venue by track, linked to summaries) below the headline |
| 2026-10-25 | Dropped the imaging+DL PubMed topic query; every paper shows its venue and impact factor (JCR for the curated list, OpenAlex 2-year citedness elsewhere) |
| 2026-10-25 | Per-source thresholds: curated journals 7, PubMed queries 9, preprints 9; journal papers with impact factor below 2 dropped (preprints and unknown-IF venues kept). Trial day Oct 24: 18 papers |
| 2026-10-25 | New PubMed query `hrpqct_dxa` (HR-pQCT and DXA on bone, no ML required) with its own threshold of 8; HR-pQCT/DXA-centred bone studies count as core in the scope and scoring prompt |
| 2026-10-25 | GO-LIVE: first real digest (2026-10-24, 65 papers incl. first-run arXiv backlog) pushed to github.com/Siyuan23333/daily_medical_image_ML_read, live at siyuan23333.github.io/daily_medical_image_ML_read, emailed to the Purdue inbox; scrontab installed (01:00 Eastern, standby, 2 h limit); trial state kept in state/trial-2026-10-25.sqlite and digests_trial/ |
| 2026-10-25 | Run time moved to 01:00 Eastern (standby kept, no deadline flag) |
| 2026-10-25 | Partition changed from a10 to a30 (group allocation holds 2 A30 GPUs) |
| 2026-10-25 | Personal values (contact address, digest recipients, Slurm account) moved from the repo to the env file before publishing the code; scrontab.txt is rendered from scrontab.template by install_scrontab.sh |
| 2026-10-25 | Manual on-demand report: `--include-today` run option, same-day report extension, run lock, and the `/daily-read-now` project skill |
| 2026-10-25 | Curated-journal papers highlighted: listed first within each track, 'journal list' pill next to the venue in the contents table and card meta, accent left border on cards, header chip with the count, 'only journal list' toggle (per-viewer, localStorage); ★ prefix in the Markdown twin and email. PubMed journal titles cleaned (subtitle and place qualifiers dropped, ISO abbreviation fallback, conservative title case) after a 176-character title broke the contents table |

## 15. Before the build can finish

User actions:
1. Add `DEEPSEEK_API_KEY` to `~/.daily_read.env`.
2. Create the public GitHub repo, a fine-grained token with Contents
   read/write on it, and add `GITHUB_TOKEN` and `GITHUB_REPO` to the env file.
3. After the first push, enable GitHub Pages (source: `gh-pages` branch) in
   the repo settings.
4. When Elsevier approves the TDM key, replace `ELSEVIER_API_KEY`.

Accepted defaults: top-N = 5, 12-hour overlap, 7-day catch-up cap, 01:00 run
time, 2 h job time limit, subject prefix `[DailyRead]`.
Score thresholds: curated journals 7, PubMed topic queries 9 (the `hrpqct_dxa` query 8), preprints 9; minimum impact factor 2 for journal papers (decided after the trial run).
