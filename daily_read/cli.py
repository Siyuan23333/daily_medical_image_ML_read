from __future__ import annotations
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from .config import load_config
from .util import redact


class RedactingFormatter(logging.Formatter):
    def __init__(self, secrets, *a, **k):
        super().__init__(*a, **k)
        self.secrets = secrets

    def format(self, record):
        return redact(super().format(record), self.secrets)


def setup_logging(cfg, verbose: bool) -> Path:
    logs = cfg.path("logs_dir")
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / f"run-{datetime.now():%Y%m%d-%H%M%S}.log"
    fmt = RedactingFormatter(cfg.secrets, "%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    root = logging.getLogger("daily_read")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in (logging.StreamHandler(sys.stderr), logging.FileHandler(path)):
        h.setFormatter(fmt)
        root.addHandler(h)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return path


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="daily_read", description="Daily digest of new ML + medical papers")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    run = sub.add_parser("run", help="collect, score, summarize, publish, email (default)")
    run.add_argument("--dry-run", action="store_true", help="collect and score only; no summaries, no publish, no email")
    run.add_argument("--no-llm", action="store_true", help="collect and prefilter only; print the candidate list")
    run.add_argument("--no-email", action="store_true")
    run.add_argument("--no-push", action="store_true")
    run.add_argument("--since", help="window start date YYYY-MM-DD (local midnight)")
    run.add_argument("--until", help="window end date YYYY-MM-DD (exclusive, local midnight)")
    run.add_argument("--limit", type=int, help="score at most N candidates (trial runs)")
    run.add_argument("--max-days", type=int, help="override max catch-up days")
    run.add_argument("--threshold", type=int, help="override every per-source threshold with this one score")
    run.add_argument("--sources", help="comma-separated subset of arxiv,biorxiv,pubmed,crossref,springer")
    rb = sub.add_parser("rebuild", help="re-render one day's page from stored results")
    rb.add_argument("--date", required=True)
    rb.add_argument("--push", action="store_true")
    rb.add_argument("--threshold", type=int, help="re-render with every per-source threshold set to this score (default: current config)")
    sub.add_parser("stats", help="score distribution and recent scored papers")
    sub.add_parser("test-email", help="send a test email")
    sub.add_parser("test-llm", help="one small DeepSeek call")
    args = ap.parse_args(argv)
    cfg = load_config()
    log_path = setup_logging(cfg, args.verbose)
    from .pipeline import Pipeline, Options
    cmd = args.cmd or "run"
    if cmd == "run":
        opts = Options(dry_run=args.dry_run, no_llm=args.no_llm, no_email=args.no_email, no_push=args.no_push, since=args.since,
                       until=args.until, limit=args.limit, max_days=args.max_days, threshold=args.threshold,
                       sources=args.sources.split(",") if args.sources else None)
        code = Pipeline(cfg, opts).run()
        print(f"log: {log_path}", file=sys.stderr)
        sys.exit(code)
    p = Pipeline(cfg, Options())
    if cmd == "rebuild":
        p.rebuild(args.date, args.push, args.threshold)
    elif cmd == "stats":
        p._print_distribution()
    elif cmd == "test-email":
        from . import mail
        ok = mail.send(cfg, f"{cfg.settings['email']['subject_prefix']} test", "DailyRead test email. If you can read this, the Purdue relay works.")
        sys.exit(0 if ok else 1)
    elif cmd == "test-llm":
        from .llm import LLM
        r = LLM(cfg)._json_call('Return {"ok": true, "model_hint": "<your model name>"}', max_tokens=50)
        print(r)
