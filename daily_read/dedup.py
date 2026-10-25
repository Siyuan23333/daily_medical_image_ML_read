from __future__ import annotations
from typing import Dict, List
from rapidfuzz import fuzz
from .models import Paper, normalize_title


def merge_duplicates(papers: List[Paper]) -> List[Paper]:
    """Merge records that refer to the same paper: same key, same DOI, or near-identical title + first author."""
    by_key: Dict[str, Paper] = {}
    for p in papers:
        if p.key in by_key:
            by_key[p.key].merge(p)
        else:
            by_key[p.key] = p
    # second pass: title similarity for records without shared identifiers (e.g. arXiv v. journal)
    merged: List[Paper] = []
    index: Dict[str, List[Paper]] = {}
    for p in by_key.values():
        nt = normalize_title(p.title)
        bucket = nt[:12]
        hit = None
        for q in index.get(bucket, []):
            if fuzz.ratio(nt, normalize_title(q.title)) >= 95 and _same_first_author(p, q):
                hit = q
                break
        if hit:
            # prefer the journal record as the survivor
            if p.venue_type == "journal" and hit.venue_type != "journal":
                p.merge(hit)
                merged[merged.index(hit)] = p
                index[bucket][index[bucket].index(hit)] = p
            else:
                hit.merge(p)
        else:
            merged.append(p)
            index.setdefault(bucket, []).append(p)
    return merged


def _same_first_author(a: Paper, b: Paper) -> bool:
    if not a.authors or not b.authors:
        return True
    fa, fb = a.authors[0].split()[-1].lower(), b.authors[0].split()[-1].lower()
    return fa == fb
