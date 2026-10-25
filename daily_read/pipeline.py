from __future__ import annotations
import json
import logging
import traceback
from collections import Counter
from datetime import datetime, date, timedelta, time as dtime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from .config import Config
from .models import Paper
from .state import State
from .dedup import merge_duplicates
from .prefilter import Prefilter
from .util import log, parse_date, iso_date, now_utc, daterange
from . import render, mail
from .publish import Publisher

SOURCES = ("arxiv", "biorxiv", "pubmed", "crossref", "springer")
CORE_TRACKS = ("bone", "radiomics", "imaging-ml")
SOURCE_CLASSES = ("curated", "pubmed_query", "preprint")


def load_thresholds(cfg: Config, override: Optional[int] = None) -> Dict[str, int]:
    """Per-source-class minimum scores from settings; a single override applies to every class."""
    rel = cfg.settings["relevance"]
    if override is not None:
        return {c: int(override) for c in SOURCE_CLASSES}
    base = rel.get("thresholds") or {}
    default = int(rel.get("threshold", 8))
    return {c: int(base.get(c, default)) for c in SOURCE_CLASSES}


def query_hits(p: Paper) -> List[str]:
    """PubMed topic queries that matched this paper (excluding the curated-journal ISSN search)."""
    hits = p.extra.get("pubmed_hits") or ([p.extra["pubmed_hit"]] if p.extra.get("pubmed_hit") else [])
    return [h for h in hits if h and h != "journal"]


def threshold_for(p: Paper, thresholds: Dict[str, int], query_thresholds: Dict[str, int]) -> int:
    """Class threshold, except that a PubMed-query paper takes the lowest per-query override among the queries that matched it."""
    cls = p.source_class
    if cls == "pubmed_query":
        over = [query_thresholds[h] for h in query_hits(p) if h in query_thresholds]
        if over:
            return min(over)
    return thresholds.get(cls, max(thresholds.values()))


def assign_days(dated: List[Tuple[str, Optional[date]]], first_open: date, horizon: date, max_days: int):
    """Map (key, digest_date) pairs to report days. Days run from first_open (capped to max_days) up to horizon.
    A paper dated before that range is a late arrival and lands in the horizon day, tagged with its original date,
    except when it is dated the horizon day itself (that is simply more of an already-reported day, see _generate_reports).
    Returns (plan: day -> [keys], late: key -> original day, truncated)."""
    earliest = max(first_open, horizon - timedelta(days=max_days - 1))
    truncated = earliest > first_open
    plan: Dict[str, List[str]] = {d.isoformat(): [] for d in daterange(earliest, horizon)} if earliest <= horizon else {}
    late: Dict[str, str] = {}
    for key, d in dated:
        d = d or horizon
        if d > horizon:
            continue
        if d < earliest and d != horizon:
            late[key] = d.isoformat()
            d = horizon
        plan.setdefault(d.isoformat(), []).append(key)
    return plan, late, truncated


def impact_ok(p: Paper, min_if: float) -> bool:
    """Impact-factor cut: journal papers whose known venue impact is below min_if are dropped.
    Preprints and venues with no known value always pass."""
    if min_if <= 0 or p.venue_type == "preprint":
        return True
    imp = p.extra.get("impact") or {}
    val = imp.get("value")
    return val is None or float(val) >= min_if


class Options:
    def __init__(self, **kw):
        self.dry_run = kw.get("dry_run", False)
        self.no_llm = kw.get("no_llm", False)
        self.no_email = kw.get("no_email", False)
        self.no_push = kw.get("no_push", False)
        self.since: Optional[str] = kw.get("since")
        self.until: Optional[str] = kw.get("until")
        self.limit: Optional[int] = kw.get("limit")
        self.max_days: Optional[int] = kw.get("max_days")
        self.threshold: Optional[int] = kw.get("threshold")
        self.sources: Optional[List[str]] = kw.get("sources")
        self.include_today: bool = kw.get("include_today", False)  # manual runs: report what is visible so far today


class Pipeline:
    def __init__(self, cfg: Config, opts: Options):
        self.cfg, self.opts = cfg, opts
        self.state = State(cfg.path("state_db"))
        self.tz = cfg.tz
        self.failed_sources: List[str] = []
        self.counts: Counter = Counter()
        self.thresholds = load_thresholds(cfg, opts.threshold)
        self.min_if = float(cfg.settings["relevance"].get("min_impact_factor") or 0)
        self.active_queries = {q["key"] for q in cfg.pubmed_queries}
        self.query_thresholds = {} if opts.threshold is not None else {q["key"]: int(q["threshold"]) for q in cfg.pubmed_queries if q.get("threshold") is not None}
        self._llm = None

    # ---------- helpers ----------
    @property
    def llm(self):
        if self._llm is None:
            from .llm import LLM
            self._llm = LLM(self.cfg)
        return self._llm

    def local_midnight(self, d: date) -> datetime:
        return datetime.combine(d, dtime(0, 0), tzinfo=self.tz)

    def threshold_for(self, p: Paper) -> int:
        return threshold_for(p, self.thresholds, self.query_thresholds)

    def passes_score(self, p: Paper, score: Optional[int]) -> bool:
        return score is not None and int(score) >= self.threshold_for(p)

    def query_active(self, p: Paper) -> bool:
        """False for papers that only came in through a PubMed topic query that has since been removed from the config."""
        if p.journal_list or p.extra.get("pubmed_hit") in (None, "", "journal"):
            return True
        return any(h in self.active_queries for h in query_hits(p))

    def eligible(self, p: Paper, score: Optional[int]) -> bool:
        return self.query_active(p) and self.passes_score(p, score) and impact_ok(p, self.min_if)

    def _horizon(self, today: date) -> date:
        """Last calendar day a run reports: yesterday normally, today for a manual --include-today run."""
        return today if self.opts.include_today else today - timedelta(days=1)

    def _refresh(self, rows: List) -> List:
        if not rows:
            return rows
        return self.state.rows("key IN (%s)" % ",".join("?" * len(rows)), tuple(r["key"] for r in rows))

    def window(self) -> Tuple[datetime, datetime]:
        w = self.cfg.settings["window"]
        end = self.local_midnight(parse_date(self.opts.until)) if self.opts.until else datetime.now(self.tz)
        if self.opts.since:
            start = self.local_midnight(parse_date(self.opts.since))
        else:
            last = self.state.last_success()
            start = (last.astimezone(self.tz) - timedelta(hours=w["overlap_hours"])) if last else (end - timedelta(days=2))
        max_days = int(self.opts.max_days or w["max_catchup_days"])
        floor = self.local_midnight(end.date() - timedelta(days=max_days))
        if start < floor:
            log.warning("window start %s capped to %s (max %d days)", start.date(), floor.date(), max_days)
            start = floor
            self.counts["window_truncated"] = 1
        return start, end

    # ---------- stages ----------
    def collect(self, start: datetime, end: datetime) -> List[Paper]:
        from .sources import arxiv, biorxiv, pubmed, crossref, springer
        mods = {"arxiv": arxiv, "biorxiv": biorxiv, "pubmed": pubmed, "crossref": crossref, "springer": springer}
        wanted = self.opts.sources or list(SOURCES)
        papers: List[Paper] = []
        for name in wanted:
            try:
                got = mods[name].collect(self.cfg, start.astimezone(self.tz), end.astimezone(self.tz))
                self.counts[f"collected_{name}"] = len(got)
                papers.extend(got)
            except Exception as e:
                log.error("source %s failed: %s", name, e)
                log.debug(traceback.format_exc())
                self.failed_sources.append(name)
        if len(self.failed_sources) == len(wanted):
            raise RuntimeError("all sources failed: " + ", ".join(self.failed_sources))
        return papers

    def resolve_pending(self, today: date) -> List[Paper]:
        """Crossref-detected papers waiting for an abstract: ask PubMed by DOI; release old ones title-only."""
        from .sources import pubmed
        rows = self.state.rows("status='pending_abstract'")
        if not rows:
            return []
        hold = int(self.cfg.settings["window"]["hold_without_abstract_days"])
        found = pubmed.lookup_by_doi(self.cfg, [r["doi"] for r in rows if r["doi"]])
        out: List[Paper] = []
        for r in rows:
            p = Paper.from_json(r["record"])
            if p.doi in found:
                p.merge(found[p.doi])
                out.append(p)
            elif (today - (parse_date(r["first_seen"]) or today)).days >= hold:
                p.extra["abstract_missing"] = True
                out.append(p)
        log.info("pending abstracts: %d waiting, %d resolved by PubMed, %d released title-only",
                 len(rows), len([p for p in out if not p.extra.get("abstract_missing")]), len([p for p in out if p.extra.get("abstract_missing")]))
        return out

    def digest_date_for(self, p: Paper, first_open: date, today: date) -> Optional[date]:
        d = parse_date(p.visible_date) or parse_date(p.published) or today
        if p.source == "arxiv" and d < first_open and (first_open - d).days <= int(self.cfg.settings["arxiv"]["extra_lookback_days"]) + 1:
            d = first_open  # arXiv announces 1-4 days after submission; not "late"
        return d

    def score_papers(self, papers: List[Paper]) -> Dict[str, Dict[str, Any]]:
        if not papers:
            return {}
        if self.opts.limit:
            papers = sorted(papers, key=lambda p: (not p.journal_list, p.journal_tier))[: self.opts.limit]
        log.info("scoring %d papers with %s", len(papers), self.cfg.settings["llm"]["model"])
        bs = int(self.cfg.settings["relevance"].get("score_batch_size", 8))
        tmpl = self.cfg.prompt("score")
        res: Dict[str, Dict[str, Any]] = {}
        for i in range(0, len(papers), bs):
            batch = papers[i:i + bs]
            got = self.llm._score_batch(batch, tmpl)
            for p in batch:
                if p.key not in got:
                    got.update(self.llm._score_batch([p], tmpl))
            for p in batch:  # persist immediately so an interrupted run keeps its scores
                r = got.get(p.key)
                if r is not None:
                    st = "scored" if self.passes_score(p, r["score"]) else "rejected"
                    self.state.upsert(p, st, score=r["score"], track=r["track"], is_review=int(r["is_review"]), reason=r["reason"], digest_date=p.extra["digest_date"])
                    self.counts["accepted" if st == "scored" else "rejected"] += 1
            res.update(got)
            if (i // bs) % 5 == 0:
                log.info("  scored %d/%d", min(i + bs, len(papers)), len(papers))
        self.counts["scored"] = len(res)
        return res

    def pick_deepdives(self, rows: List) -> List:
        n = int(self.cfg.settings["relevance"]["top_n_deepdive"])
        def k(r):
            p = Paper.from_json(r["record"])
            return (-(r["score"] or 0), 0 if (r["track"] in CORE_TRACKS) else 1, p.journal_tier if p.journal_list else 4, 0 if p.venue_type == "journal" else 1)
        return sorted(rows, key=k)[:n]

    # ---------- main ----------
    def run(self) -> int:
        start, end = self.window()
        today = end.astimezone(self.tz).date()
        run_id = self.state.start_run(start, end, self.opts.dry_run)
        log.info("run %d: window %s -> %s (%s), thresholds %s, per-query %s, min IF %g%s", run_id, start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes"),
                 "DRY RUN" if self.opts.dry_run else "live", self.thresholds, self.query_thresholds, self.min_if, " [no-llm]" if self.opts.no_llm else "")
        try:
            self._run(start, end, today)
        except Exception as e:
            log.error("run failed: %s", e)
            log.debug(traceback.format_exc())
            self.state.finish_run(run_id, "failed", dict(self.counts), str(e)[:1000])
            if not (self.opts.dry_run or self.opts.no_email):
                mail.send(self.cfg, f"{self.cfg.settings['email']['subject_prefix']} run failed", f"DailyRead run {run_id} failed:\n\n{e}\n\nCounts: {json.dumps(dict(self.counts), indent=1)}")
            return 1
        status = "dry" if (self.opts.dry_run or self.opts.no_llm) else "ok"
        self.state.finish_run(run_id, status, dict(self.counts))
        if status == "ok":
            try:
                self.state.backup(self.cfg.path("state_backup_dir"))
            except Exception as e:
                log.warning("state backup failed: %s", e)
        log.info("run %d finished (%s): %s", run_id, status, json.dumps(dict(self.counts)))
        if self._llm:
            log.info("llm usage: %s", self._llm.usage)
        return 0

    def _run(self, start: datetime, end: datetime, today: date) -> None:
        latest = self.state.latest_report_date()
        first_open = (parse_date(latest) + timedelta(days=1)) if latest else start.astimezone(self.tz).date()
        # 1-2 collect, merge, resolve pending
        papers = merge_duplicates(self.collect(start, end) + self.resolve_pending(today))
        self.counts["collected_unique"] = len(papers)
        # 3 skip known, defer future-dated, hold abstract-less journal papers
        known = self.state.known_keys([p.key for p in papers])
        fresh, cached_scored = [], []
        for p in papers:
            d = self.digest_date_for(p, first_open, today)
            if self.cfg.settings["window"].get("deferral", True) and d > self._horizon(today):
                self.counts["deferred"] += 1
                continue
            p.extra["digest_date"] = d.isoformat()
            row = known.get(p.key)
            if row is None:
                fresh.append(p)
            elif row["status"] == "pending_abstract" and (p.abstract or p.extra.get("abstract_missing")):
                fresh.append(p)
            elif row["status"] == "scored":
                cached_scored.append(p)  # scored in an earlier dry run; keep for reporting
            else:
                self.counts["already_known"] += 1
        # 4 prefilter
        keep, dropped = Prefilter(self.cfg).apply(fresh)
        for p, why in dropped:
            self.state.upsert(p, "excluded", reason=why)
        self.counts["prefilter_dropped"] = len(dropped)
        to_score, held = [], []
        for p in keep:
            if p.source in ("crossref",) and not p.abstract and not p.extra.get("abstract_missing"):
                held.append(p)
            else:
                to_score.append(p)
        for p in held:
            self.state.upsert(p, "pending_abstract")
        self.counts["held_for_abstract"] = len(held)
        self.counts["to_score"] = len(to_score)
        if self.opts.no_llm:
            self._print_plan(to_score, today, first_open)
            return
        # 5 score
        results = self.score_papers(to_score)
        for p in to_score:
            if p.key not in results and not self.opts.limit:
                self.state.upsert(p, "scored", score=None, reason="scoring failed", digest_date=p.extra["digest_date"])
        for p in cached_scored:
            self.state.upsert(p, "scored", digest_date=p.extra["digest_date"])
        if self.opts.dry_run:
            self._print_distribution()
            return
        # 6-10 reports, oldest day first
        self._generate_reports(today, first_open, start, end)

    def _print_plan(self, to_score: List[Paper], today: date, first_open: date) -> None:
        by_src = Counter(p.source.split("+")[0] for p in to_score)
        by_day = Counter(p.extra["digest_date"] for p in to_score)
        log.info("candidates to score by source: %s", dict(by_src))
        log.info("candidates by digest date: %s", dict(sorted(by_day.items())))
        for p in sorted(to_score, key=lambda p: (p.extra["digest_date"], not p.journal_list))[:400]:
            log.info("  %s | %-14s | %-26s | %s", p.extra["digest_date"], p.source[:14], p.venue[:26], p.title[:90])

    def _print_distribution(self) -> None:
        dist = self.state.score_distribution()
        total = sum(dist.values())
        log.info("score distribution over %d scored papers (all runs):", total)
        for s in range(10, -1, -1):
            n = dist.get(s, 0)
            log.info("  %2d | %-40s %d", s, "#" * min(40, n), n)
        by_cls: Counter = Counter()
        pass_cls: Counter = Counter()
        for r in self.state.rows("score IS NOT NULL"):
            p = Paper.from_json(r["record"])
            by_cls[p.source_class] += 1
            if self.passes_score(p, r["score"]):
                pass_cls[p.source_class] += 1
        log.info("thresholds %s, min impact factor %g (applied to journal papers at report time)", self.thresholds, self.min_if)
        for c in SOURCE_CLASSES:
            log.info("  %-13s %4d scored, %4d at or above threshold", c, by_cls[c], pass_cls[c])
        rows = self.state.rows("score IS NOT NULL ORDER BY score DESC, updated DESC LIMIT 60")
        for r in rows:
            log.info("  [%2d] %-10s %-24s %s  -- %s", r["score"], r["track"] or "", (r["venue"] or "")[:24], (r["title"] or "")[:80], (r["reason"] or "")[:60])

    # ---------- reports ----------
    def _generate_reports(self, today: date, first_open: date, start: datetime, end: datetime) -> None:
        horizon = self._horizon(today)
        rows, below, stale = [], [], []
        for r in self.state.rows("status='scored' AND score IS NOT NULL"):
            p = Paper.from_json(r["record"])
            if not self.query_active(p):
                stale.append(r)
            elif self.passes_score(p, r["score"]):
                rows.append(r)
            else:
                below.append(r)
        if below:  # scored under an older/looser rule; settle them so they are not re-examined every run
            self.state.set_status([r["key"] for r in below], "rejected")
            self.counts["rejected"] += len(below)
        if stale:
            self.state.set_status([r["key"] for r in stale], "excluded", reason="pubmed query removed from config")
            self.counts["stale_query"] = len(stale)
        rows = self._apply_impact_cut(self._annotate_impact(rows))
        if not rows and first_open > horizon:
            log.info("nothing to report")
            return
        max_days = int(self.opts.max_days or self.cfg.settings["window"]["max_catchup_days"])
        by_key = {r["key"]: r for r in rows}
        plan_keys, late, truncated = assign_days([(r["key"], parse_date(r["digest_date"])) for r in rows], first_open, horizon, max_days)
        plan: Dict[str, List] = {day: [by_key[k] for k in keys] for day, keys in plan_keys.items()}
        pub = Publisher(self.cfg)
        do_push = pub.enabled and not self.opts.no_push
        if not pub.enabled:
            log.warning("publishing disabled (GITHUB_REPO/GITHUB_TOKEN missing); pages stay local")
        digests = self.cfg.path("digests_dir")
        digests.mkdir(parents=True, exist_ok=True)
        window_str = f"{start.astimezone(self.tz):%Y-%m-%d %H:%M} to {end.astimezone(self.tz):%Y-%m-%d %H:%M} {self.tz}"
        days = sorted(plan)
        for i, day in enumerate(days):
            new_rows = plan[day]
            # a day that already has a report (a manual --include-today run earlier, or a second run the same day)
            # keeps its papers and grows; the page is regenerated and re-sent with the number of additions
            existing = self.state.rows("status='reported' AND digest_date=?", (day,))
            new_keys = {r["key"] for r in new_rows}
            day_rows = [r for r in existing if r["key"] not in new_keys] + new_rows
            n_new = len(new_rows) if existing else 0
            log.info("report %s: %d papers%s", day, len(day_rows), f" ({n_new} new since the earlier report)" if existing else "")
            day_rows, headline = self._enrich_day(day, day_rows, None)
            note = ""
            if truncated and i == 0:
                note = f"earlier days were skipped (catch-up capped at {max_days} days)"
            if existing:
                note = (note + "; " if note else "") + f"{n_new} added since the earlier report for this day"
            n_late = sum(1 for r in day_rows if r["key"] in late)
            if n_late:
                note = (note + "; " if note else "") + f"{n_late} late arrival{'s' if n_late > 1 else ''} from earlier days"
            # render
            prev_date = days[i - 1] if i > 0 else max((r["date"] for r in self.state.reports() if r["date"] < day), default="")
            out = render.render_day(self.cfg, day, [self._with_late(r, late) for r in day_rows], headline, note, self.failed_sources, window_str, prev_date=prev_date or "", next_date=days[i + 1] if i + 1 < len(days) else "")
            html_path, md_path = digests / f"{day}.html", digests / f"{day}.md"
            html_path.write_text(out["html"])
            md_path.write_text(out["md"])
            url = pub.page_url(day) if pub.enabled else html_path.as_uri()
            self.state.save_report(day, n_papers=len(day_rows), counts=out["counts"], html_path=str(html_path), md_path=str(md_path), url=url, headline=headline, note=note)
            self.state.set_status([r["key"] for r in day_rows], "reported", digest_date=day)
            for k, orig in late.items():
                if any(r["key"] == k for r in day_rows):
                    self.state.set_status([k], "reported", late_of=orig)
            # index + publish
            index_path = digests / "index.html"
            index_path.write_text(render.render_index(self.cfg, self.state.reports()))
            if do_push:
                try:
                    pub.publish([html_path, index_path], f"DailyRead {day}")
                    live = pub.wait_live(url)
                    self.state.mark_report(day, pushed=1 if live else 0)
                    if not live:
                        log.warning("page not live yet at %s", url)
                except Exception as e:
                    log.error("publish failed for %s: %s", day, e)
            # email
            if not self.opts.no_email:
                counts_str = ", ".join(f"{k} {v}" for k, v in sorted(out["counts"].items(), key=lambda kv: -kv[1]))
                subject = f"{self.cfg.settings['email']['subject_prefix']} {day}: {len(day_rows)} papers" + (f" (+{n_new} new)" if existing else "") + (f" ({counts_str})" if counts_str else "")
                em = render.render_email(self.cfg, day, url, len(day_rows), headline, out["deepdives"], self.failed_sources, n_curated=out.get("n_curated", 0))
                if mail.send(self.cfg, subject, em["text"], em["html"]):
                    self.state.mark_report(day, emailed=1)
            self.counts["reports"] += 1

    def _apply_impact_cut(self, rows: List) -> List:
        """Drop journal papers below the minimum impact factor (status -> excluded). Rows must already carry extra.impact."""
        if self.min_if <= 0 or not rows:
            return rows
        keep = []
        for r in rows:
            p = Paper.from_json(r["record"])
            if impact_ok(p, self.min_if):
                keep.append(r)
                continue
            val = (p.extra.get("impact") or {}).get("value")
            self.state.set_status([r["key"]], "excluded", reason=f"impact factor {val} below {self.min_if:g}")
            self.counts["impact_cut"] += 1
            log.info("  IF cut: %s (%s, IF %s, score %s)", p.title[:70], p.venue, val, r["score"])
        return keep

    def _enrich_day(self, day: str, day_rows: List, headline: Optional[str]) -> Tuple[List, str]:
        """Fill missing summaries, top-N deep dives and (when headline is None) the headline for one day's rows."""
        for r in day_rows:
            if not r["summary"]:
                p = Paper.from_json(r["record"])
                try:
                    s = self.llm.summary(p)
                except Exception as e:
                    log.warning("summary failed for %s: %s", p.key, e)
                    s = (p.abstract or "")[:600]
                self.state.set_status([r["key"]], r["status"], summary=s)
        day_rows = self._refresh(day_rows)
        from . import fulltext
        for r in self.pick_deepdives(day_rows):
            if r["deepdive"]:
                continue
            p = Paper.from_json(r["record"])
            text, status = fulltext.fetch(self.cfg, p)
            try:
                dd = self.llm.deepdive(p, text or p.abstract or "", status)
            except Exception as e:
                log.warning("deepdive failed for %s: %s", p.key, e)
                continue
            self.counts[f"fulltext_{status.split(':')[0]}"] += 1
            self.state.set_status([r["key"]], r["status"], deepdive=dd, fulltext_status=status, record=p.to_json())
        day_rows = self._annotate_impact(self._refresh(day_rows))
        if headline is None:
            headline = ""
            if day_rows:
                items = [dict(title=r["title"], venue=r["venue"], track=r["track"], score=r["score"], summary=(r["summary"] or "")[:400]) for r in sorted(day_rows, key=lambda r: -(r["score"] or 0))]
                try:
                    headline = self.llm.headline(day, items)
                except Exception as e:
                    log.warning("headline failed: %s", e)
        return day_rows, headline

    def _annotate_impact(self, rows: List) -> List:
        """Attach venue impact metrics to each paper record (cached in the state DB); returns refreshed rows."""
        if not rows:
            return rows
        from .venues import Venues
        v = Venues(self.cfg, self.state)
        changed = 0
        for r in rows:
            p = Paper.from_json(r["record"])
            if "impact" not in p.extra:
                p.extra["impact"] = v.impact(p)
                self.state.set_status([r["key"]], r["status"], record=p.to_json())
                changed += 1
        if changed:
            log.info("impact metrics looked up for %d papers", changed)
            return self.state.rows("key IN (%s)" % ",".join("?" * len(rows)), tuple(r["key"] for r in rows))
        return rows

    @staticmethod
    def _with_late(row, late: Dict[str, str]):
        if row["key"] not in late:
            return row
        d = dict(row)
        d["late_of"] = late[row["key"]]
        return d

    # ---------- rebuild ----------
    def rebuild(self, day: str, push: bool, threshold: Optional[int] = None) -> None:
        rep = self.state.report(day)
        if not rep:
            raise SystemExit(f"no report for {day}")
        if threshold is not None:
            self.thresholds, self.query_thresholds = load_thresholds(self.cfg, threshold), {}
        rows = self._annotate_impact(self.state.rows("status='reported' AND digest_date=?", (day,)))
        kept = [r for r in rows if self.eligible(Paper.from_json(r["record"]), r["score"])]
        if len(kept) != len(rows):
            log.info("rebuild %s: %d of %d reported papers no longer pass (thresholds %s, min IF %g)", day, len(rows) - len(kept), len(rows), self.thresholds, self.min_if)
        # a changed paper set needs a new headline and possibly new summaries/deep dives; otherwise reuse the stored ones
        headline = rep["headline"] if (len(kept) == (rep["n_papers"] or 0) and rep["headline"]) else None
        rows, headline = self._enrich_day(day, kept, headline)
        digests = self.cfg.path("digests_dir")
        out = render.render_day(self.cfg, day, rows, headline, rep["note"] or "", [], "rebuild")
        (digests / f"{day}.html").write_text(out["html"])
        (digests / f"{day}.md").write_text(out["md"])
        (digests / "index.html").write_text(render.render_index(self.cfg, self.state.reports()))
        self.state.save_report(day, n_papers=len(rows), counts=out["counts"], headline=headline, generated_at=rep["generated_at"])
        log.info("rebuilt %s (%d papers, %d deep dives)", day, len(rows), len(out["deepdives"]))
        pub = Publisher(self.cfg)
        if push and pub.enabled:
            pub.publish([digests / f"{day}.html", digests / "index.html"], f"DailyRead rebuild {day}")
