from __future__ import annotations
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from jinja2 import Environment, FileSystemLoader, select_autoescape
from .models import Paper
from .venues import impact_label, impact_title


def _env(cfg) -> Environment:
    env = Environment(loader=FileSystemLoader(str(cfg.root / "templates")), autoescape=select_autoescape(["html", "j2"]))
    return env


def view_model(row, cfg) -> Dict[str, Any]:
    p = Paper.from_json(row["record"])
    track = row["track"] or "other"
    labels = {t["key"]: t["label"] for t in cfg.settings["tracks"]}
    dd = json.loads(row["deepdive"]) if row["deepdive"] else None
    authors = p.authors[:3]
    authors_short = ", ".join(authors) + (" et al." if len(p.authors) > 3 else "")
    fts = row["fulltext_status"] or "abstract_only"
    ft_label = {"abstract_only": "from abstract only"}.get(fts, "from full text via " + fts.split(":", 1)[-1])
    summary = row["summary"] or ""
    one_liner = re.split(r"(?<=[.!?])\s+", summary.strip())[0] if summary else ""
    return dict(
        title=p.title, url=p.url or (f"https://doi.org/{p.doi}" if p.doi else "#"), doi=p.doi, pdf_url=p.pdf_url, arxiv_id=p.arxiv_id, pmid=p.pmid,
        venue=p.venue, published=p.published, authors_short=authors_short, track=track, track_label=labels.get(track, "Other"),
        score=row["score"], is_review=bool(row["is_review"]), late_of=row["late_of"], summary=summary, one_liner=one_liner,
        deepdive=dd, fulltext_label=ft_label, anchor=re.sub(r"[^a-z0-9]+", "-", p.key.lower()).strip("-"),
        impact=p.extra.get("impact"), impact_label=impact_label(p.extra.get("impact")), impact_label_long=impact_label(p.extra.get("impact"), long=True),
        impact_title=impact_title(p.extra.get("impact")), is_preprint=(p.venue_type == "preprint"),
        curated=bool(p.journal_list),
    )


def render_day(cfg, date: str, rows: List, headline: str, note: str, failed_sources: List[str], window: str,
               prev_date: str = "", next_date: str = "") -> Dict[str, str]:
    env = _env(cfg)
    items = [view_model(r, cfg) for r in rows]
    items.sort(key=lambda x: (not x["curated"], -(x["score"] or 0), x["title"]))  # curated journals first within each track
    n_curated = sum(1 for x in items if x["curated"])
    deep = [x for x in items if x["deepdive"]]
    by_track: Dict[str, List[Dict[str, Any]]] = {}
    for x in items:
        by_track.setdefault(x["track"], []).append(x)
    counts = {k: len(v) for k, v in by_track.items()}
    tracks = list(cfg.settings["tracks"]) + ([{"key": "other", "label": "Other"}] if "other" in by_track else [])
    ctx = dict(date=date, date_long=datetime.strptime(date, "%Y-%m-%d").strftime("%A, %d %B %Y"), n_papers=len(items),
               headline=headline, note=note, failed_sources=failed_sources, tracks=tracks, counts=counts, by_track=by_track, n_curated=n_curated,
               deepdives=deep, generated_at=datetime.now(cfg.tz).strftime("%Y-%m-%d %H:%M %Z"), model=cfg.settings["llm"]["model"],
               window=window, prev_date=prev_date, next_date=next_date)
    html = env.get_template("day.html.j2").render(**ctx)
    md = env.get_template("day.md.j2").render(**ctx)
    return {"html": html, "md": md, "counts": counts, "deepdives": deep, "n_curated": n_curated}


def render_index(cfg, reports: List) -> str:
    env = _env(cfg)
    rs = []
    for r in reports:
        counts = json.loads(r["counts"]) if r["counts"] else {}
        rs.append(dict(date=r["date"], n_papers=r["n_papers"], headline=r["headline"] or "",
                       counts_str=", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))))
    return env.get_template("index.html.j2").render(reports=rs)


def render_email(cfg, date: str, url: str, n_papers: int, headline: str, deepdives: List[Dict[str, Any]], failed_sources: List[str], n_curated: int = 0) -> Dict[str, str]:
    env = _env(cfg)
    ctx = dict(date=date, url=url, n_papers=n_papers, headline=headline, deepdives=deepdives, failed_sources=failed_sources, n_curated=n_curated)
    return {"text": env.get_template("email.txt.j2").render(**ctx), "html": env.get_template("email.html.j2").render(**ctx)}
