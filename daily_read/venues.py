from __future__ import annotations
"""Venue impact metrics: curated JCR values from config, OpenAlex 2-year mean citedness for everything else (cached)."""
from typing import Any, Dict, List, Optional
import yaml
from .models import Paper
from .util import session, get_with_backoff, log, now_utc

OPENALEX = "https://api.openalex.org/sources"


class Venues:
    def __init__(self, cfg, state):
        self.cfg, self.state = cfg, state
        data = yaml.safe_load((cfg.root / "config" / "impact_factors.yaml").read_text()) or {}
        self.by_issn: Dict[str, Dict[str, Any]] = {}
        self.by_name: Dict[str, Dict[str, Any]] = {}
        for j in data.get("journals", []):
            for i in j.get("issn", []):
                self.by_issn[str(i).upper()] = j
            self.by_name[j["name"].lower()] = j
        self.journal_issns: Dict[str, List[str]] = {}
        for j in cfg.journals:
            for key in (j["name"], j.get("short")):
                if key:
                    self.journal_issns[key.lower()] = [str(i).upper() for i in j.get("issn", [])]
        self._s = None

    def _issns(self, p: Paper) -> List[str]:
        out = [str(i).upper() for i in p.extra.get("issns", []) if i]
        out += self.journal_issns.get((p.venue or "").lower(), [])
        return list(dict.fromkeys(out))

    def impact(self, p: Paper) -> Optional[Dict[str, Any]]:
        if p.venue_type == "preprint":
            return None
        issns = self._issns(p)
        for i in issns:
            j = self.by_issn.get(i)
            if j:
                return {"value": float(j["jif"]), "source": "JCR", "year": str(j.get("year", "")), "approx": False}
        j = self.by_name.get((p.venue or "").lower())
        if j:
            return {"value": float(j["jif"]), "source": "JCR", "year": str(j.get("year", "")), "approx": False}
        for i in issns:
            hit = self._openalex(i, p.venue)
            if hit is not None:
                return hit
        if p.venue and len(p.venue) > 6 and not issns:
            return self._openalex("", p.venue)
        return None

    def _openalex(self, issn: str, name: str) -> Optional[Dict[str, Any]]:
        key = ("issn:" + issn) if issn else ("name:" + name.lower())
        row = self.state.venue_get(key)
        if row is not None:
            return {"value": row["metric"], "source": "OpenAlex", "year": row["year"] or "", "approx": True} if row["metric"] is not None else None
        if self._s is None:
            self._s = session()
        try:
            if issn:
                r = get_with_backoff(self._s, f"{OPENALEX}/issn:{issn}", params={"mailto": self.cfg.settings["fulltext"]["crossref_mailto"]}, timeout=30, tries=2)
                d = r.json() if r.status_code == 200 else None
            else:
                r = get_with_backoff(self._s, OPENALEX, params={"search": name, "per-page": 1, "mailto": self.cfg.settings["fulltext"]["crossref_mailto"]}, timeout=30, tries=2)
                res = r.json().get("results", []) if r.status_code == 200 else []
                d = res[0] if res and res[0].get("display_name", "").lower()[:12] == name.lower()[:12] else None
        except Exception as e:  # metrics are decoration; never fail a run over them
            log.info("openalex lookup failed for %s: %s", key, e)
            d = None
        metric = None
        if d:
            m = (d.get("summary_stats") or {}).get("2yr_mean_citedness")
            metric = round(float(m), 1) if m is not None else None
        self.state.venue_put(key, d.get("display_name") if d else name, metric, "OpenAlex", str(now_utc().year - 1))
        return {"value": metric, "source": "OpenAlex", "year": str(now_utc().year - 1), "approx": True} if metric is not None else None

    def annotate(self, papers: List[Paper]) -> int:
        n = 0
        for p in papers:
            if "impact" in p.extra:
                continue
            p.extra["impact"] = self.impact(p)
            n += 1
        return n


def impact_label(imp: Optional[Dict[str, Any]], long: bool = False) -> str:
    if not imp or imp.get("value") is None:
        return ""
    v = imp["value"]
    txt = f"IF {v:.1f}" if not imp.get("approx") else f"IF\u2248{v:.1f}"
    if long:
        txt += f" ({'JCR ' + imp['year'] if imp['source'] == 'JCR' else 'OpenAlex 2-year citedness'})"
    return txt


def impact_title(imp: Optional[Dict[str, Any]]) -> str:
    if not imp:
        return ""
    if imp["source"] == "JCR":
        return f"Journal Impact Factor {imp['year']} (Clarivate JCR)"
    return "OpenAlex 2-year mean citedness, approximates the impact factor"
