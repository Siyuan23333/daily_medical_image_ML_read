from __future__ import annotations
import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


def normalize_title(t: str) -> str:
    t = re.sub(r"<[^>]+>", " ", t or "")
    t = re.sub(r"[^a-z0-9 ]", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def normalize_doi(d: Optional[str]) -> Optional[str]:
    if not d:
        return None
    d = d.strip()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d, flags=re.I)
    d = re.sub(r"^doi:\s*", "", d, flags=re.I)
    return d.lower() or None


@dataclass
class Paper:
    title: str
    abstract: str = ""
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    pmid: Optional[str] = None
    pmcid: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    venue: str = ""                 # journal name, "arXiv", "medRxiv", "bioRxiv"
    venue_type: str = "journal"     # journal | preprint
    source: str = ""                # collector name
    url: str = ""
    pdf_url: str = ""
    published: str = ""             # publication / posting date YYYY-MM-DD
    visible_date: str = ""          # date it became visible in the source (digest date basis)
    journal_list: bool = False
    journal_tier: int = 3
    open_access: Optional[bool] = None
    categories: List[str] = field(default_factory=list)
    pub_types: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.doi = normalize_doi(self.doi)
        self.title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", self.title or "")).strip()

    @property
    def key(self) -> str:
        if self.doi:
            return "doi:" + self.doi
        if self.arxiv_id:
            return "arxiv:" + re.sub(r"v\d+$", "", self.arxiv_id)
        if self.pmid:
            return "pmid:" + self.pmid
        return "title:" + hashlib.sha1(normalize_title(self.title).encode()).hexdigest()[:16]

    @property
    def text_for_filter(self) -> str:
        return f"{self.title}\n{self.abstract}"

    @property
    def source_class(self) -> str:
        """Threshold class: curated (journal list) | preprint (arXiv, medRxiv, bioRxiv) | pubmed_query (everything else)."""
        if self.journal_list:
            return "curated"
        if self.venue_type == "preprint" or (self.source or "").split("+")[0] in ("arxiv", "medrxiv", "biorxiv"):
            return "preprint"
        return "pubmed_query"

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @staticmethod
    def from_json(s: str) -> "Paper":
        return Paper(**json.loads(s))

    def merge(self, other: "Paper") -> "Paper":
        """Fill gaps in self from other; prefer journal metadata over preprint."""
        for f in ("doi", "arxiv_id", "pmid", "pmcid", "url", "pdf_url", "published", "visible_date"):
            if not getattr(self, f) and getattr(other, f):
                setattr(self, f, getattr(other, f))
        if len(other.abstract or "") > len(self.abstract or ""):
            self.abstract = other.abstract
        if not self.authors and other.authors:
            self.authors = other.authors
        if other.journal_list and not self.journal_list:
            self.journal_list, self.journal_tier, self.venue, self.venue_type = True, other.journal_tier, other.venue, other.venue_type
        if self.open_access is None:
            self.open_access = other.open_access
        self.categories = sorted(set(self.categories) | set(other.categories))
        self.pub_types = sorted(set(self.pub_types) | set(other.pub_types))
        self.extra.update({k: v for k, v in other.extra.items() if k not in self.extra})
        self.source = self.source if self.source == other.source else f"{self.source}+{other.source}"
        return self
