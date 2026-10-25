from __future__ import annotations
import re
import time
from typing import Any, Dict, Optional
import feedparser
from rapidfuzz import fuzz
from ..models import Paper, normalize_title
from ..util import session, get_with_backoff


def find(cfg, p: Paper) -> Optional[Dict[str, Any]]:
    """Look for an arXiv or medRxiv/bioRxiv preprint of a journal paper by title (and first author)."""
    nt = normalize_title(p.title)
    words = [w for w in nt.split() if len(w) > 3][:8]
    if len(words) < 3:
        return None
    s = session()
    # arXiv
    q = " AND ".join(f"ti:{w}" for w in words[:6])
    r = get_with_backoff(s, "https://export.arxiv.org/api/query", params={"search_query": q, "max_results": 3}, timeout=60, tries=2)
    time.sleep(3)
    if r.status_code == 200:
        for e in feedparser.parse(r.text).entries:
            if fuzz.ratio(nt, normalize_title(e.title)) >= 90 and _author_ok(p, [a.name for a in e.get("authors", [])]):
                pdf = next((l.href for l in e.get("links", []) if l.get("type") == "application/pdf"), "")
                if pdf:
                    return {"server": "arxiv", "id": e.id.rsplit("/", 1)[-1], "pdf_url": pdf, "url": e.link}
    # medRxiv / bioRxiv via Europe PMC preprint index
    r = get_with_backoff(s, "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                         params={"query": f'SRC:PPR AND TITLE:"{" ".join(words[:6])}"', "format": "json", "pageSize": 5}, timeout=30, tries=2)
    if r.status_code == 200:
        for it in r.json().get("resultList", {}).get("result", []):
            if fuzz.ratio(nt, normalize_title(it.get("title", ""))) >= 90:
                doi = it.get("doi", "")
                m = re.match(r"10\.1101/(.+)", doi)
                if m:
                    for server in ("medrxiv", "biorxiv"):
                        pdf = f"https://www.{server}.org/content/{doi}v1.full.pdf"
                        return {"server": server, "id": doi, "pdf_url": pdf, "url": f"https://www.{server}.org/content/{doi}v1"}
    return None


def _author_ok(p: Paper, names) -> bool:
    if not p.authors or not names:
        return True
    last = p.authors[0].split()[-1].lower()
    return any(last in n.lower() for n in names)
