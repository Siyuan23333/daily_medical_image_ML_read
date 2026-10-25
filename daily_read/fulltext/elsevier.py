from __future__ import annotations
import re
import xml.etree.ElementTree as ET
from typing import Optional
from ..util import session, get_with_backoff, log


def fulltext(cfg, doi: str) -> Optional[str]:
    key = cfg.secrets.get("ELSEVIER_API_KEY")
    if not key:
        return None
    headers = {"X-ELS-APIKey": key, "Accept": "text/xml"}
    tok = cfg.secrets.get("ELSEVIER_INSTTOKEN")
    if tok:
        headers["X-ELS-Insttoken"] = tok
    s = session()
    r = get_with_backoff(s, f"https://api.elsevier.com/content/article/doi/{doi}", headers=headers, timeout=60, tries=2)
    if r.status_code != 200:
        log.info("elsevier api %s for %s", r.status_code, doi)
        return None
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        return None
    parts = []
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag == "section-title":
            parts.append("\n## " + "".join(el.itertext()).strip() + "\n")
        elif tag == "para":
            parts.append("".join(el.itertext()).strip())
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(x for x in parts if x))
    return text if len(text) > 2000 else None
