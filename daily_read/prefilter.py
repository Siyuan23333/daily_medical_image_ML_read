from __future__ import annotations
import re
from typing import List, Tuple
from .models import Paper

REVIEW_HINT = re.compile(r"\b(systematic review|meta-analysis|scoping review|narrative review|a review|survey of|: a survey|an overview)\b", re.I)


class Prefilter:
    def __init__(self, cfg):
        self.med = cfg.compiled_keywords("medical")
        self.weak = cfg.compiled_keywords("medical_weak")
        self.ml = cfg.compiled_keywords("ml")
        self.excl = cfg.compiled_keywords("exclude_title")
        self.bone_img = cfg.compiled_keywords("bone_imaging")

    def _any(self, pats, text: str) -> bool:
        return any(p.search(text) for p in pats)

    def check(self, p: Paper) -> Tuple[bool, str]:
        if self._any(self.excl, p.title):
            return False, "excluded title pattern"
        if len(p.title) < 15:
            return False, "title too short"
        text = p.text_for_filter
        if p.journal_list or p.source == "pubmed":
            return True, "journal list / pubmed topic query"
        has_strong, has_ml = self._any(self.med, text), self._any(self.ml, text)
        n_weak = sum(1 for r in self.weak if r.search(text))
        prim = p.extra.get("primary_category", "")
        has_med = has_strong or n_weak >= 2 or (prim.startswith(("eess.IV", "q-bio")) and n_weak >= 1)
        if p.source == "arxiv":
            return (has_med, "medical term" if has_med else "no strong medical term")
        if self._any(self.bone_img, text) and p.source in ("medrxiv", "biorxiv"):
            return True, "bone densitometry term"
        if p.source == "medrxiv":
            return (has_ml, "ml term" if has_ml else "no ml term")
        if p.source == "biorxiv":
            ok = has_ml and has_strong
            return ok, "ml+medical" if ok else "needs ml and medical terms"
        return (has_med and has_ml), "generic rule"

    def apply(self, papers: List[Paper]) -> Tuple[List[Paper], List[Tuple[Paper, str]]]:
        keep, drop = [], []
        for p in papers:
            ok, why = self.check(p)
            (keep if ok else drop).append(p if ok else (p, why))
        return keep, drop
