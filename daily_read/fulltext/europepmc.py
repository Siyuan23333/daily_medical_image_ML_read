from __future__ import annotations
import re
import xml.etree.ElementTree as ET
from typing import Optional
from ..util import session, get_with_backoff

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"


def pmcid_for_doi(doi: str) -> Optional[str]:
    s = session()
    r = get_with_backoff(s, f"{BASE}/search", params={"query": f'DOI:"{doi}"', "format": "json", "pageSize": 1}, timeout=30, tries=2)
    if r.status_code != 200:
        return None
    res = r.json().get("resultList", {}).get("result", [])
    return res[0].get("pmcid") if res else None


def fulltext_by_pmcid(pmcid: str) -> Optional[str]:
    s = session()
    r = get_with_backoff(s, f"{BASE}/{pmcid}/fullTextXML", timeout=60, tries=2)
    if r.status_code != 200 or not r.content:
        return None
    return jats_to_text(r.content)


def jats_to_text(content: bytes) -> Optional[str]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return None
    body = root.find(".//body")
    if body is None:
        return None
    parts = []
    for el in body.iter():
        tag = el.tag.split("}")[-1]
        if tag == "title":
            parts.append("\n## " + "".join(el.itertext()).strip() + "\n")
        elif tag == "p":
            parts.append("".join(el.itertext()).strip())
    text = "\n".join(x for x in parts if x)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text if len(text) > 500 else None
