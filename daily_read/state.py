from __future__ import annotations
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from .models import Paper
from .util import now_utc

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
  key TEXT PRIMARY KEY,
  doi TEXT, arxiv_id TEXT, pmid TEXT, title TEXT,
  venue TEXT, source TEXT, visible_date TEXT,
  status TEXT NOT NULL,              -- pending_abstract | scored | rejected | reported | excluded
  score INTEGER, track TEXT, is_review INTEGER, reason TEXT,
  summary TEXT, deepdive TEXT, fulltext_status TEXT,
  digest_date TEXT, late_of TEXT,
  first_seen TEXT NOT NULL, updated TEXT NOT NULL,
  record TEXT NOT NULL               -- Paper JSON
);
CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi);
CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status);
CREATE INDEX IF NOT EXISTS idx_papers_digest ON papers(digest_date);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started TEXT NOT NULL, finished TEXT,
  window_start TEXT, window_end TEXT,
  status TEXT NOT NULL,              -- running | ok | failed | dry
  counts TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS venues (
  key TEXT PRIMARY KEY, name TEXT, metric REAL, source TEXT, year TEXT, fetched TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
  date TEXT PRIMARY KEY,
  generated_at TEXT NOT NULL, n_papers INTEGER, counts TEXT,
  html_path TEXT, md_path TEXT, url TEXT, headline TEXT,
  pushed INTEGER DEFAULT 0, emailed INTEGER DEFAULT 0, note TEXT
);
"""


class State:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # ---- papers ----
    def known_keys(self, keys: Iterable[str]) -> Dict[str, sqlite3.Row]:
        keys = list(keys)
        out: Dict[str, sqlite3.Row] = {}
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            q = f"SELECT * FROM papers WHERE key IN ({','.join('?' * len(chunk))})"
            for row in self.db.execute(q, chunk):
                out[row["key"]] = row
        return out

    def find_by_doi(self, doi: str) -> Optional[sqlite3.Row]:
        return self.db.execute("SELECT * FROM papers WHERE doi=?", (doi,)).fetchone()

    def upsert(self, p: Paper, status: str, **fields: Any) -> None:
        ts = now_utc().isoformat()
        row = self.db.execute("SELECT first_seen FROM papers WHERE key=?", (p.key,)).fetchone()
        first_seen = row["first_seen"] if row else ts
        cols = dict(key=p.key, doi=p.doi, arxiv_id=p.arxiv_id, pmid=p.pmid, title=p.title, venue=p.venue,
                    source=p.source, visible_date=p.visible_date, status=status, first_seen=first_seen, updated=ts,
                    record=p.to_json())
        for k in ("score", "track", "is_review", "reason", "summary", "deepdive", "fulltext_status", "digest_date", "late_of"):
            if k in fields:
                v = fields[k]
                cols[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
        names = list(cols)
        sql = f"INSERT INTO papers ({','.join(names)}) VALUES ({','.join('?' * len(names))}) " \
              f"ON CONFLICT(key) DO UPDATE SET " + ",".join(f"{n}=excluded.{n}" for n in names if n not in ("key", "first_seen"))
        self.db.execute(sql, [cols[n] for n in names])
        self.db.commit()

    def rows(self, where: str = "1=1", params: tuple = ()) -> List[sqlite3.Row]:
        return self.db.execute(f"SELECT * FROM papers WHERE {where}", params).fetchall()

    def set_status(self, keys: Iterable[str], status: str, **fields: Any) -> None:
        ts = now_utc().isoformat()
        sets = ["status=?", "updated=?"]
        vals: List[Any] = [status, ts]
        for k, v in fields.items():
            sets.append(f"{k}=?")
            vals.append(json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
        for k in keys:
            self.db.execute(f"UPDATE papers SET {','.join(sets)} WHERE key=?", vals + [k])
        self.db.commit()

    # ---- runs ----
    def last_success(self) -> Optional[datetime]:
        row = self.db.execute("SELECT MAX(finished) AS f FROM runs WHERE status='ok'").fetchone()
        return datetime.fromisoformat(row["f"]) if row and row["f"] else None

    def start_run(self, window_start: datetime, window_end: datetime, dry: bool) -> int:
        cur = self.db.execute("INSERT INTO runs (started, window_start, window_end, status) VALUES (?,?,?,?)",
                              (now_utc().isoformat(), window_start.isoformat(), window_end.isoformat(), "running"))
        self.db.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, counts: Dict[str, Any], error: str = "") -> None:
        self.db.execute("UPDATE runs SET finished=?, status=?, counts=?, error=? WHERE id=?",
                        (now_utc().isoformat(), status, json.dumps(counts), error, run_id))
        self.db.commit()

    # ---- reports ----
    def report(self, d: str) -> Optional[sqlite3.Row]:
        return self.db.execute("SELECT * FROM reports WHERE date=?", (d,)).fetchone()

    def reports(self) -> List[sqlite3.Row]:
        return self.db.execute("SELECT * FROM reports ORDER BY date DESC").fetchall()

    def latest_report_date(self) -> Optional[str]:
        row = self.db.execute("SELECT MAX(date) AS d FROM reports").fetchone()
        return row["d"] if row else None

    def save_report(self, d: str, **fields: Any) -> None:
        fields.setdefault("generated_at", now_utc().isoformat())
        if "counts" in fields and not isinstance(fields["counts"], str):
            fields["counts"] = json.dumps(fields["counts"])
        names = ["date"] + list(fields)
        sql = f"INSERT INTO reports ({','.join(names)}) VALUES ({','.join('?' * len(names))}) " \
              f"ON CONFLICT(date) DO UPDATE SET " + ",".join(f"{n}=excluded.{n}" for n in names if n != "date")
        self.db.execute(sql, [d] + list(fields.values()))
        self.db.commit()

    def mark_report(self, d: str, **fields: Any) -> None:
        sets = ",".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE reports SET {sets} WHERE date=?", list(fields.values()) + [d])
        self.db.commit()

    # ---- venues ----
    def venue_get(self, key: str) -> Optional[sqlite3.Row]:
        return self.db.execute("SELECT * FROM venues WHERE key=?", (key,)).fetchone()

    def venue_put(self, key: str, name: Optional[str], metric: Optional[float], source: str, year: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO venues (key,name,metric,source,year,fetched) VALUES (?,?,?,?,?,?)",
                        (key, name, metric, source, year, now_utc().isoformat()))
        self.db.commit()

    def backup(self, dest_dir: Path) -> None:
        dest_dir = Path(dest_dir).expanduser()
        dest_dir.mkdir(parents=True, exist_ok=True)
        self.db.commit()
        shutil.copy2(self.path, dest_dir / self.path.name)

    def score_distribution(self) -> Dict[int, int]:
        out: Dict[int, int] = {}
        for row in self.db.execute("SELECT score, COUNT(*) AS n FROM papers WHERE score IS NOT NULL GROUP BY score"):
            out[int(row["score"])] = int(row["n"])
        return out
