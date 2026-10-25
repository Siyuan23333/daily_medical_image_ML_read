from __future__ import annotations
from typing import Optional, Tuple
from ..util import session, get_with_backoff


def best_pdf(cfg, doi: str) -> Tuple[Optional[str], Optional[bool]]:
    s = session()
    r = get_with_backoff(s, f"https://api.unpaywall.org/v2/{doi}", params={"email": cfg.settings["fulltext"]["unpaywall_email"]}, timeout=30, tries=2)
    if r.status_code != 200:
        return None, None
    d = r.json()
    loc = d.get("best_oa_location") or {}
    url = loc.get("url_for_pdf") or None
    if not url:
        for l in d.get("oa_locations", []) or []:
            if l.get("url_for_pdf"):
                url = l["url_for_pdf"]
                break
    return url, bool(d.get("is_oa"))
