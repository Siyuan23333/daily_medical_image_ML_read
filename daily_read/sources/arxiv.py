from __future__ import annotations
import time
from datetime import datetime, timedelta
from typing import List
import feedparser
from ..models import Paper
from ..util import session, get_with_backoff, log

API = "https://export.arxiv.org/api/query"


def collect(cfg, window_start: datetime, window_end: datetime) -> List[Paper]:
    a = cfg.settings["arxiv"]
    cats = " OR ".join(f"cat:{c}" for c in a["categories"])
    start = (window_start - timedelta(days=a.get("extra_lookback_days", 4))).strftime("%Y%m%d%H%M")
    end = window_end.strftime("%Y%m%d%H%M")
    query = f"({cats}) AND submittedDate:[{start} TO {end}]"
    s = session()
    out: List[Paper] = []
    offset, page = 0, int(a.get("page_size", 200))
    while True:
        r = get_with_backoff(s, API, params={"search_query": query, "start": offset, "max_results": page,
                                             "sortBy": "submittedDate", "sortOrder": "descending"}, timeout=90)
        if r.status_code != 200:
            raise RuntimeError(f"arXiv HTTP {r.status_code}")
        feed = feedparser.parse(r.text)
        entries = feed.entries
        if not entries:
            break
        for e in entries:
            aid = e.id.rsplit("/", 1)[-1]
            pdf = next((l.href for l in e.get("links", []) if l.get("type") == "application/pdf"), "")
            doi = getattr(e, "arxiv_doi", None)
            out.append(Paper(
                title=e.title, abstract=(e.get("summary") or "").replace("\n", " ").strip(),
                arxiv_id=aid, doi=doi, authors=[x.name for x in e.get("authors", [])][:30],
                venue="arXiv", venue_type="preprint", source="arxiv", url=e.link, pdf_url=pdf,
                published=e.published[:10], visible_date=e.published[:10],
                categories=[t.term for t in e.get("tags", [])],
                extra={"primary_category": getattr(e, "arxiv_primary_category", {}).get("term", ""), "comment": getattr(e, "arxiv_comment", "")},
            ))
        total = int(feed.feed.get("opensearch_totalresults", 0) or 0)
        offset += len(entries)
        if offset >= total or len(entries) < page:
            break
        time.sleep(a.get("delay_seconds", 3))
    log.info("arxiv: %d entries (query window %s..%s)", len(out), start, end)
    return out
