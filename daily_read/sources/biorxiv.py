from __future__ import annotations
from datetime import datetime
from typing import List
from ..models import Paper
from ..util import session, get_with_backoff, log

API = "https://api.biorxiv.org/details/{server}/{start}/{end}/{cursor}"


def collect(cfg, window_start: datetime, window_end: datetime) -> List[Paper]:
    b = cfg.settings["biorxiv"]
    s = session()
    out: List[Paper] = []
    for server in b["servers"]:
        cursor = 0
        while True:
            url = API.format(server=server, start=window_start.date().isoformat(), end=window_end.date().isoformat(), cursor=cursor)
            r = get_with_backoff(s, url, timeout=90)
            if r.status_code != 200:
                raise RuntimeError(f"{server} HTTP {r.status_code}")
            data = r.json()
            coll = data.get("collection", []) or []
            for it in coll:
                if b.get("new_versions_only", True) and str(it.get("version", "1")) != "1":
                    continue
                doi = it.get("doi")
                out.append(Paper(
                    title=it.get("title", ""), abstract=it.get("abstract", ""), doi=doi,
                    authors=[x.strip() for x in (it.get("authors") or "").split(";") if x.strip()][:30],
                    venue="medRxiv" if server == "medrxiv" else "bioRxiv", venue_type="preprint", source=server,
                    url=f"https://www.{server}.org/content/{doi}v{it.get('version','1')}",
                    pdf_url=f"https://www.{server}.org/content/{doi}v{it.get('version','1')}.full.pdf",
                    published=it.get("date", ""), visible_date=it.get("date", ""),
                    categories=[it.get("category", "")], open_access=True,
                    extra={"published_doi": it.get("published", "")},
                ))
            msgs = data.get("messages", [{}])
            total = int(msgs[0].get("total", 0) or 0) if msgs else 0
            cursor += len(coll)
            if not coll or cursor >= total:
                break
    log.info("biorxiv/medrxiv: %d new v1 preprints", len(out))
    return out
