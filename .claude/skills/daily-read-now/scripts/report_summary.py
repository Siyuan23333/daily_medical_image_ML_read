#!/usr/bin/env python3
"""Print the latest DailyRead reports from the state database: counts, URL, publish/email status, headline,
curated-journal papers and deep dives. Standard library only. Usage: report_summary.py [--last N] [--date YYYY-MM-DD]"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path


def project_root(explicit: str = "") -> Path:
    """--root, then DAILY_READ_ROOT, then the project this skill is installed in, then the current directory."""
    import os
    here = Path(__file__).resolve()
    cands = [explicit, os.environ.get("DAILY_READ_ROOT", ""), here.parents[4] if len(here.parents) > 4 else "", Path.cwd()]
    for cand in cands:
        if cand and (Path(cand) / "run_daily.sh").exists():
            return Path(cand)
    sys.exit("DailyRead project root not found: pass --root <dir> (the directory holding run_daily.sh)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--last", type=int, default=2)
    ap.add_argument("--date")
    ap.add_argument("--root", default="", help="project directory holding run_daily.sh")
    a = ap.parse_args()
    root = project_root(a.root)
    db = root / "state" / "daily_read.sqlite"
    if not db.exists():
        sys.exit(f"no state database at {db}")
    c = sqlite3.connect(str(db))
    c.row_factory = sqlite3.Row
    if a.date:
        reports = c.execute("SELECT * FROM reports WHERE date=?", (a.date,)).fetchall()
    else:
        reports = c.execute("SELECT * FROM reports ORDER BY date DESC LIMIT ?", (a.last,)).fetchall()
    if not reports:
        print("no reports yet")
        return
    run = c.execute("SELECT started, finished, status, counts FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    if run:
        print(f"last run: {run['status']} ({run['started'][:16]} -> {(run['finished'] or '')[:16]} UTC)")
    for r in reports:
        counts = json.loads(r["counts"]) if r["counts"] else {}
        print(f"\n{r['date']}  {r['n_papers']} papers  pushed={'yes' if r['pushed'] else 'no'}  emailed={'yes' if r['emailed'] else 'no'}")
        print(f"  url: {r['url']}")
        if r["note"]:
            print(f"  note: {r['note']}")
        print("  tracks: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])))
        if r["headline"]:
            print(f"  headline: {r['headline']}")
        papers = c.execute("SELECT title, venue, track, score, deepdive, record FROM papers WHERE status='reported' AND digest_date=? ORDER BY score DESC", (r["date"],)).fetchall()
        curated = [p for p in papers if json.loads(p["record"]).get("journal_list")]
        if curated:
            print(f"  curated journals ({len(curated)}):")
            for p in curated:
                print(f"    - [{p['score']}] {p['title']} ({p['venue']})")
        deep = [p for p in papers if p["deepdive"]]
        if deep:
            print(f"  deep dives ({len(deep)}):")
            for p in deep:
                print(f"    - {p['title']} ({p['venue']}, {p['track']})")


if __name__ == "__main__":
    main()
