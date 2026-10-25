from __future__ import annotations
import json
import re
import time
from typing import Any, Dict, List, Optional
from openai import OpenAI
from .models import Paper
from .util import log

TRACKS = {"imaging-ml", "radiomics", "bone", "ehr-nlp", "other"}


class LLM:
    def __init__(self, cfg):
        self.cfg = cfg
        s = cfg.settings["llm"]
        key = cfg.secrets.get("DEEPSEEK_API_KEY")
        if not key:
            raise RuntimeError("DEEPSEEK_API_KEY missing")
        self.client = OpenAI(api_key=key, base_url=s["base_url"], timeout=s.get("timeout_seconds", 120), max_retries=0)
        self.model = s["model"]
        self.deepdive_model = s.get("deepdive_model", self.model)
        self.temperature = float(s.get("temperature", 0.2))
        self.max_retries = int(s.get("max_retries", 3))
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}

    def _json_call(self, prompt: str, model: Optional[str] = None, max_tokens: int = 2000) -> Dict[str, Any]:
        last: Optional[Exception] = None
        for i in range(self.max_retries):
            try:
                r = self.client.chat.completions.create(
                    model=model or self.model, temperature=self.temperature, max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                    messages=[{"role": "system", "content": "You are a careful scientific assistant. Respond with valid JSON only."},
                              {"role": "user", "content": prompt}])
                self.usage["calls"] += 1
                if r.usage:
                    self.usage["prompt_tokens"] += r.usage.prompt_tokens or 0
                    self.usage["completion_tokens"] += r.usage.completion_tokens or 0
                txt = r.choices[0].message.content or "{}"
                txt = re.sub(r"^```(json)?|```$", "", txt.strip(), flags=re.M).strip()
                return json.loads(txt)
            except Exception as e:  # rate limit, timeout, bad JSON
                last = e
                log.warning("llm call failed (%d/%d): %s", i + 1, self.max_retries, str(e)[:200])
                time.sleep(3 * (i + 1))
        raise RuntimeError(f"LLM call failed after retries: {last}")

    # ---- scoring ----
    def score(self, papers: List[Paper]) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        bs = int(self.cfg.settings["relevance"].get("score_batch_size", 8))
        tmpl = self.cfg.prompt("score")
        for i in range(0, len(papers), bs):
            batch = papers[i:i + bs]
            res = self._score_batch(batch, tmpl)
            missing = [p for p in batch if p.key not in res]
            for p in missing:  # retry singly
                res.update(self._score_batch([p], tmpl))
            out.update(res)
        return out

    def _score_batch(self, batch: List[Paper], tmpl: str) -> Dict[str, Dict[str, Any]]:
        ids = {f"P{i+1}": p for i, p in enumerate(batch)}
        blocks = []
        for pid, p in ids.items():
            abstract = (p.abstract or "(no abstract available)")[:3000]
            blocks.append(f"[{pid}] TITLE: {p.title}\nVENUE: {p.venue}\nABSTRACT: {abstract}")
        prompt = tmpl.format(scope=self.cfg.scope, papers="\n\n".join(blocks))
        try:
            data = self._json_call(prompt, max_tokens=200 * len(batch) + 200)
        except RuntimeError as e:
            log.error("scoring batch failed: %s", e)
            return {}
        out: Dict[str, Dict[str, Any]] = {}
        for r in data.get("results", []):
            p = ids.get(str(r.get("id", "")).strip())
            if not p:
                continue
            try:
                score = max(0, min(10, int(round(float(r.get("score", 0))))))
            except (TypeError, ValueError):
                continue
            track = str(r.get("track", "other")).strip().lower()
            out[p.key] = {"score": score, "track": track if track in TRACKS else "other",
                          "is_review": bool(r.get("is_review", False)), "reason": str(r.get("reason", ""))[:200]}
        return out

    # ---- summaries ----
    def summary(self, p: Paper, text: Optional[str] = None) -> str:
        prompt = self.cfg.prompt("summary").format(title=p.title, venue=p.venue, text=(text or p.abstract or "(no abstract)")[:12000])
        data = self._json_call(prompt, max_tokens=600)
        return str(data.get("summary", "")).strip()

    def deepdive(self, p: Paper, text: str, fulltext_status: str) -> Dict[str, Any]:
        limit = int(self.cfg.settings["llm"].get("max_fulltext_chars", 90000))
        prompt = self.cfg.prompt("deepdive").format(title=p.title, venue=p.venue, fulltext_status=fulltext_status, text=text[:limit])
        data = self._json_call(prompt, model=self.deepdive_model, max_tokens=2500)
        keys = ("overview", "datasets", "method", "validation", "results", "limitations", "availability")
        return {k: data.get(k, [] if k not in ("overview", "availability") else "") for k in keys}

    def headline(self, date: str, items: List[Dict[str, Any]]) -> str:
        lines = [f"- [{it['track']}, score {it['score']}] {it['title']} ({it['venue']}): {it['summary']}" for it in items]
        prompt = self.cfg.prompt("headline").format(date=date, papers="\n".join(lines)[:30000])
        data = self._json_call(prompt, max_tokens=500)
        return str(data.get("headline", "")).strip()
