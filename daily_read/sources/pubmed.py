from __future__ import annotations
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, List, Optional
from ..models import Paper
from ..util import session, get_with_backoff, log

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
REVIEW_TYPES = {"Review", "Systematic Review", "Meta-Analysis"}
SKIP_TYPES = {"Editorial", "Comment", "Erratum", "Published Erratum", "Letter", "News", "Retraction of Publication", "Retracted Publication"}


def _params(cfg, **kw) -> Dict[str, str]:
    p = {"db": "pubmed", "retmode": "json", "tool": "DailyRead", "email": cfg.settings["fulltext"]["unpaywall_email"]}
    key = cfg.secrets.get("NCBI_API_KEY")
    if key:
        p["api_key"] = key
    p.update({k: str(v) for k, v in kw.items()})
    return p


def _delay(cfg) -> float:
    return 0.12 if cfg.secrets.has("NCBI_API_KEY") else 0.4


def esearch_ids(cfg, s, term: str, mindate: str, maxdate: str, datetype: str = "edat") -> List[str]:
    ids: List[str] = []
    retstart, retmax = 0, 500
    while True:
        r = get_with_backoff(s, EUTILS + "esearch.fcgi", params=_params(cfg, term=term, datetype=datetype, mindate=mindate, maxdate=maxdate, retmax=retmax, retstart=retstart), timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"PubMed esearch HTTP {r.status_code}")
        res = r.json().get("esearchresult", {})
        batch = res.get("idlist", [])
        ids.extend(batch)
        count = int(res.get("count", 0))
        retstart += len(batch)
        time.sleep(_delay(cfg))
        if not batch or retstart >= count:
            break
    return ids


def efetch(cfg, s, pmids: List[str]) -> List[Paper]:
    out: List[Paper] = []
    for i in range(0, len(pmids), 200):
        chunk = pmids[i:i + 200]
        r = get_with_backoff(s, EUTILS + "efetch.fcgi", params=_params(cfg, id=",".join(chunk), retmode="xml"), timeout=120)
        if r.status_code != 200:
            raise RuntimeError(f"PubMed efetch HTTP {r.status_code}")
        out.extend(parse_pubmed_xml(r.content, cfg))
        time.sleep(_delay(cfg))
    return out


def _date_from(el: Optional[ET.Element]) -> str:
    if el is None:
        return ""
    y, m, d = el.findtext("Year"), el.findtext("Month") or "01", el.findtext("Day") or "01"
    if not y:
        return ""
    months = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06", "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"}
    m = months.get(m, m)
    return f"{y}-{int(m):02d}-{int(d):02d}"


_SMALL_WORDS = {"of", "and", "the", "in", "for", "on", "a", "an", "to", "at", "by", "with", "from", "de", "der", "und", "et", "la", "le", "des", "du", "fur", "für", "e", "di", "da", "van", "von", "&"}
_KEEP_LOWER = {"npj"}


def _titlecase_journal(s: str) -> str:
    """Conservative title case for PubMed's lowercase journal titles; acronyms, mixed-case and small words are left alone."""
    out = []
    for i, w in enumerate(s.split(" ")):
        core = w.strip("(),.;:")
        if not core or any(ch.isupper() for ch in core[1:]) or any(ch.isdigit() for ch in core) or core in _KEEP_LOWER \
                or (i > 0 and core.lower() in _SMALL_WORDS):
            out.append(w)
        else:
            out.append("-".join(part[:1].upper() + part[1:] for part in w.split("-")))
    return " ".join(out)


def clean_journal_title(title: str, iso_abbrev: str = "", max_len: int = 70) -> str:
    """Turn PubMed's catalogue title into a display name: drop the ' : subtitle' and trailing place/publisher
    qualifiers such as '(Bellingham, Wash.)', fall back to the ISO abbreviation when still too long, then title-case."""
    t = re.sub(r"\s+", " ", title or "").strip()
    t = re.split(r"\s+[:=]\s+", t, maxsplit=1)[0].strip()
    t = re.sub(r"\s*\([^()]*\)\s*$", "", t).strip(" .,;")
    if (not t or len(t) > max_len) and iso_abbrev:
        t = iso_abbrev.strip()
    return _titlecase_journal(t)


def parse_pubmed_xml(content: bytes, cfg) -> List[Paper]:
    by_issn = cfg.journal_by_issn()
    root = ET.fromstring(content)
    out: List[Paper] = []
    for art in root.findall(".//PubmedArticle"):
        med = art.find("MedlineCitation")
        a = med.find("Article") if med is not None else None
        if a is None:
            continue
        pmid = med.findtext("PMID") or ""
        title = "".join(a.find("ArticleTitle").itertext()) if a.find("ArticleTitle") is not None else ""
        abs_parts = []
        for at in a.findall("Abstract/AbstractText"):
            label = at.get("Label")
            txt = "".join(at.itertext()).strip()
            abs_parts.append(f"{label}: {txt}" if label else txt)
        abstract = " ".join(abs_parts)
        journal = a.find("Journal")
        jtitle = clean_journal_title(journal.findtext("Title") if journal is not None else "",
                                     (journal.findtext("ISOAbbreviation") if journal is not None else "") or med.findtext("MedlineJournalInfo/MedlineTA") or "")
        issn_els = journal.findall("ISSN") if journal is not None else []
        issns = [e.text.upper() for e in issn_els if e.text]
        linking = med.findtext("MedlineJournalInfo/ISSNLinking")
        if linking:
            issns.append(linking.upper())
        jl = next((by_issn[i] for i in issns if i in by_issn), None)
        ids = {e.get("IdType"): e.text for e in art.findall("PubmedData/ArticleIdList/ArticleId")}
        doi = ids.get("doi") or next((e.text for e in a.findall("ELocationID") if e.get("EIdType") == "doi"), None)
        pub_types = [pt.text for pt in a.findall("PublicationTypeList/PublicationType") if pt.text]
        authors = []
        for au in a.findall("AuthorList/Author")[:30]:
            ln, ini, coll = au.findtext("LastName"), au.findtext("Initials"), au.findtext("CollectiveName")
            if ln:
                authors.append(f"{ini + ' ' if ini else ''}{ln}")
            elif coll:
                authors.append(coll)
        hist = {h.get("PubStatus"): _date_from(h) for h in art.findall("PubmedData/History/PubMedPubDate")}
        visible = hist.get("entrez") or hist.get("pubmed") or hist.get("medline") or ""
        pubdate = _date_from(a.find("ArticleDate")) or _date_from(journal.find("JournalIssue/PubDate") if journal is not None else None) or visible
        out.append(Paper(
            title=title, abstract=abstract, doi=doi, pmid=pmid, pmcid=ids.get("pmc"), authors=authors,
            venue=(jl.get("short") or jl["name"]) if jl else jtitle, venue_type="journal", source="pubmed",
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", published=pubdate, visible_date=visible,
            journal_list=bool(jl), journal_tier=jl.get("tier", 3) if jl else 3,
            open_access=True if ids.get("pmc") else (jl.get("open_access") if jl else None),
            pub_types=pub_types, extra={"issns": issns},
        ))
    return out


def collect(cfg, window_start: datetime, window_end: datetime) -> List[Paper]:
    s = session()
    mindate, maxdate = window_start.strftime("%Y/%m/%d"), window_end.strftime("%Y/%m/%d")
    ids: Dict[str, List[str]] = {}
    # 1) curated journals not covered by the Springer API
    issns = [i for j in cfg.journals if j.get("detection") != "springer" for i in j["issn"]]
    term = " OR ".join(f'"{i}"[IS]' for i in issns)
    for pmid in esearch_ids(cfg, s, term, mindate, maxdate):
        ids.setdefault(pmid, []).append("journal")
    # 2) standing topic queries (a paper can match several; all are kept for per-query thresholds)
    for q in cfg.pubmed_queries:
        for pmid in esearch_ids(cfg, s, q["term"], mindate, maxdate):
            ids.setdefault(pmid, []).append(q["key"])
    papers = efetch(cfg, s, list(ids)) if ids else []
    for p in papers:
        hits = ids.get(p.pmid or "", [])
        p.extra["pubmed_hit"] = hits[0] if hits else ""
        p.extra["pubmed_hits"] = hits
    papers = [p for p in papers if not (set(p.pub_types) & SKIP_TYPES and not p.abstract)]
    log.info("pubmed: %d ids -> %d papers (%s..%s)", len(ids), len(papers), mindate, maxdate)
    return papers


def lookup_by_doi(cfg, dois: List[str]) -> Dict[str, Paper]:
    """Fetch PubMed records for specific DOIs (used to fill abstracts of Crossref-detected papers)."""
    s = session()
    found: Dict[str, Paper] = {}
    for doi in dois:
        try:
            r = get_with_backoff(s, EUTILS + "esearch.fcgi", params=_params(cfg, term=f'"{doi}"[AID]', retmax=1), timeout=60)
            idl = r.json().get("esearchresult", {}).get("idlist", []) if r.status_code == 200 else []
            time.sleep(_delay(cfg))
            if idl:
                for p in efetch(cfg, s, idl):
                    if p.doi:
                        found[p.doi] = p
        except Exception as e:  # keep going for the rest
            log.warning("pubmed lookup failed for %s: %s", doi, e)
    return found
