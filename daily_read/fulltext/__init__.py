"""Full-text retrieval in the agreed order: open access -> preprint -> publisher API -> abstract only."""
from __future__ import annotations
from typing import Optional, Tuple
from ..models import Paper
from ..util import log
from . import unpaywall, europepmc, springer_oa, preprint_match, elsevier, pdf


def fetch(cfg, p: Paper) -> Tuple[str, str]:
    """Return (text, status). status is one of: oa:<route>, preprint:<arxiv|medrxiv|biorxiv>, publisher:<name>, abstract_only."""
    order = cfg.settings["fulltext"]["order"]
    for step in order:
        try:
            if step == "open_access":
                res = _open_access(cfg, p)
            elif step == "preprint":
                res = _preprint(cfg, p)
            elif step == "publisher_api":
                res = _publisher(cfg, p)
            else:
                res = None
        except Exception as e:  # any route failing just moves to the next
            log.warning("fulltext step %s failed for %s: %s", step, p.key, str(e)[:150])
            res = None
        if res and len(res[0]) > 2000:
            return res
    return (p.abstract or "", "abstract_only")


def _open_access(cfg, p: Paper) -> Optional[Tuple[str, str]]:
    if p.source in ("arxiv", "medrxiv", "biorxiv") and p.pdf_url:
        t = pdf.text_from_url(p.pdf_url)
        if t:
            return t, f"oa:{p.source}-pdf"
    if p.pmcid:
        t = europepmc.fulltext_by_pmcid(p.pmcid)
        if t:
            return t, "oa:europepmc"
    if p.doi and p.doi.startswith("10.1038/") or (p.doi and p.doi.startswith("10.1007/")):
        t = springer_oa.fulltext(cfg, p.doi)
        if t:
            return t, "oa:springer-oa-api"
    if p.doi:
        pmcid = europepmc.pmcid_for_doi(p.doi)
        if pmcid:
            t = europepmc.fulltext_by_pmcid(pmcid)
            if t:
                p.pmcid = pmcid
                return t, "oa:europepmc"
        url, is_oa = unpaywall.best_pdf(cfg, p.doi)
        if is_oa is not None:
            p.open_access = is_oa
        if url:
            t = pdf.text_from_url(url)
            if t:
                return t, "oa:unpaywall-pdf"
    return None


def _preprint(cfg, p: Paper) -> Optional[Tuple[str, str]]:
    if p.source in ("arxiv", "medrxiv", "biorxiv"):
        return None
    hit = preprint_match.find(cfg, p)
    if hit:
        t = pdf.text_from_url(hit["pdf_url"])
        if t:
            p.extra["preprint_match"] = hit
            return t, f"preprint:{hit['server']}"
    return None


def _publisher(cfg, p: Paper) -> Optional[Tuple[str, str]]:
    if p.doi and p.doi.startswith("10.1016/"):
        t = elsevier.fulltext(cfg, p.doi)
        if t:
            return t, "publisher:elsevier"
    return None
