from __future__ import annotations
import re
from typing import Optional
import fitz  # PyMuPDF
from ..util import session, get_with_backoff, log

MAX_BYTES = 40 * 1024 * 1024


def text_from_url(url: str) -> Optional[str]:
    s = session()
    s.headers["Accept"] = "application/pdf,*/*"
    r = get_with_backoff(s, url, timeout=120, tries=2)
    if r.status_code != 200 or len(r.content) > MAX_BYTES:
        return None
    ctype = r.headers.get("Content-Type", "")
    if "pdf" not in ctype and not r.content[:5].startswith(b"%PDF"):
        return None
    return text_from_bytes(r.content)


def text_from_bytes(data: bytes) -> Optional[str]:
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:
        log.info("pdf open failed: %s", e)
        return None
    pages = []
    for page in doc:
        pages.append(page.get_text("text"))
    text = "\n".join(pages)
    text = re.sub(r"-\n(?=[a-z])", "", text)        # de-hyphenate line breaks
    text = re.sub(r"[ \t]+\n", "\n", text)
    # drop references section if clearly marked
    m = re.search(r"\n\s*(References|REFERENCES|Bibliography)\s*\n", text)
    if m and m.start() > len(text) * 0.4:
        text = text[:m.start()]
    return text if len(text) > 2000 else None
