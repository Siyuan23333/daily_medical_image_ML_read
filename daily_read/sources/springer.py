from __future__ import annotations
from datetime import datetime
from typing import List
from ..models import Paper
from ..util import session, get_with_backoff, log

API = "https://api.springernature.com/meta/v2/json"  # free tier allows at most p=25 per page
SKIP_TYPES = {"Erratum", "Correction", "EditorialNotes", "BookReview", "Letter", "News"}


def collect(cfg, window_start: datetime, window_end: datetime) -> List[Paper]:
    key = cfg.secrets.get("SPRINGER_METADATA_API_KEY")
    if not key:
        raise RuntimeError("SPRINGER_METADATA_API_KEY missing")
    s = session()
    out: List[Paper] = []
    failures, n_journals = 0, sum(1 for j in cfg.journals if j.get("detection") == "springer")
    for j in cfg.journals:
        if j.get("detection") != "springer":
            continue
        start = 1
        while True:
            q = f"journalid:{j['springer_id']} onlinedatefrom:{window_start.date()} onlinedateto:{window_end.date()}"
            r = get_with_backoff(s, API, params={"q": q, "p": 25, "s": start, "api_key": key}, timeout=90)
            if r.status_code == 404:  # the API answers 404 when a journal has no records in the window
                break
            if r.status_code != 200:
                log.warning("springer: HTTP %d for %s; skipping journal", r.status_code, j["name"])
                failures += 1
                break
            data = r.json()
            recs = data.get("records", [])
            for it in recs:
                ctype = it.get("contentType", "")
                if ctype in SKIP_TYPES:
                    continue
                doi = it.get("doi")
                url = next((u["value"] for u in it.get("url", []) if u.get("format") == "html"), "") or f"https://doi.org/{doi}"
                out.append(Paper(
                    title=it.get("title", ""), abstract=(it.get("abstract") or "").replace("Abstract", "", 1).strip(), doi=doi,
                    authors=[c.get("creator", "") for c in it.get("creators", [])][:30],
                    venue=j.get("short") or j["name"], venue_type="journal", source="springer", url=url,
                    published=it.get("onlineDate") or it.get("publicationDate", ""), visible_date=it.get("onlineDate") or it.get("publicationDate", ""),
                    journal_list=True, journal_tier=j.get("tier", 3),
                    open_access=(str(it.get("openaccess", "false")).lower() == "true") or bool(j.get("open_access")),
                    pub_types=[ctype] if ctype else [], extra={"genre": it.get("genre", "")},
                ))
            total = int(data.get("result", [{}])[0].get("total", 0) or 0)
            start += len(recs)
            if not recs or start > total:
                break
    if n_journals and failures == n_journals:
        raise RuntimeError("Springer API failed for every journal")
    log.info("springer: %d articles (%d journal(s) failed)", len(out), failures)
    return out
