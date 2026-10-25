from __future__ import annotations
import re
from datetime import datetime
from typing import List
from ..models import Paper
from ..util import session, get_with_backoff, log

API = "https://api.crossref.org/journals/{issn}/works"
SKIP_TITLE = re.compile(r"^(erratum|correction|corrigendum|retraction|editorial|issue information|table of contents|masthead|editorial board)", re.I)


def collect(cfg, window_start: datetime, window_end: datetime) -> List[Paper]:
    s = session()
    mailto = cfg.settings["fulltext"]["crossref_mailto"]
    out: List[Paper] = []
    for j in cfg.journals:
        if j.get("detection") != "crossref":
            continue
        issn = j.get("crossref_issn") or j["issn"][0]
        params = {"filter": f"from-created-date:{window_start.date()},until-created-date:{window_end.date()},type:journal-article",
                  "rows": 200, "select": "DOI,title,author,created,issued,published-online,container-title,abstract,URL,link,is-referenced-by-count,license",
                  "mailto": mailto}
        r = get_with_backoff(s, API.format(issn=issn), params=params, timeout=90)
        if r.status_code != 200:
            log.warning("crossref %s HTTP %d", j["name"], r.status_code)
            continue
        for it in r.json()["message"]["items"]:
            title = (it.get("title") or [""])[0]
            if not title or SKIP_TITLE.search(title):
                continue
            created = it["created"]["date-time"][:10]
            online = it.get("published-online", {}).get("date-parts", [[None]])[0]
            pub = "-".join(f"{x:02d}" if i else str(x) for i, x in enumerate(online)) if online and online[0] else created
            abstract = re.sub(r"<[^>]+>", " ", it.get("abstract") or "").strip()
            pdf = next((l["URL"] for l in it.get("link", []) if l.get("content-type") == "application/pdf"), "")
            lic = [l.get("URL", "") for l in it.get("license", [])]
            oa = True if j.get("open_access") or any("creativecommons" in u for u in lic) else None
            out.append(Paper(
                title=title, abstract=abstract, doi=it["DOI"],
                authors=[f"{a.get('given','')} {a.get('family','')}".strip() for a in it.get("author", [])][:30],
                venue=j.get("short") or j["name"], venue_type="journal", source="crossref",
                url=it.get("URL") or f"https://doi.org/{it['DOI']}", pdf_url=pdf,
                published=pub, visible_date=created, journal_list=True, journal_tier=j.get("tier", 3), open_access=oa,
            ))
    log.info("crossref: %d journal articles", len(out))
    return out
