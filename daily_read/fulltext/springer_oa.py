from __future__ import annotations
from typing import Optional
from ..util import session, get_with_backoff
from .europepmc import jats_to_text


def fulltext(cfg, doi: str) -> Optional[str]:
    key = cfg.secrets.get("SPRINGER_OPEN_ACCESS_API_KEY")
    if not key:
        return None
    s = session()
    r = get_with_backoff(s, "https://api.springernature.com/openaccess/jats", params={"q": f"doi:{doi}", "api_key": key}, timeout=60, tries=2)
    if r.status_code != 200:
        return None
    return jats_to_text(r.content)
