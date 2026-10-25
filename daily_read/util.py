from __future__ import annotations
import logging
import time
from datetime import datetime, date, timedelta, timezone
from typing import Optional
import requests
from requests.adapters import HTTPAdapter

log = logging.getLogger("daily_read")
USER_AGENT = "DailyRead/0.1 (academic digest pipeline)"
CONTACT = ""  # set from CONTACT_EMAIL in the env file by config.load_config


def user_agent() -> str:
    return USER_AGENT + (f"; mailto:{CONTACT}" if CONTACT else "")
SECRET_ENV_NAMES = ("DEEPSEEK_API_KEY", "GITHUB_TOKEN", "SPRINGER_METADATA_API_KEY", "SPRINGER_OPEN_ACCESS_API_KEY",
                    "ELSEVIER_API_KEY", "ELSEVIER_INSTTOKEN", "NCBI_API_KEY")


def session(retries: int = 2) -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = user_agent()
    adapter = HTTPAdapter(max_retries=retries, pool_connections=4, pool_maxsize=4)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def get_with_backoff(s: requests.Session, url: str, *, params=None, headers=None, timeout=60, tries=4, sleep=2.0):
    """GET with exponential backoff on 429/5xx and network errors. Returns the Response (any status)."""
    last: Optional[Exception] = None
    for i in range(tries):
        try:
            r = s.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504):
                last = RuntimeError(f"HTTP {r.status_code} from {url.split('?')[0]}")
                time.sleep(sleep * (2 ** i))
                continue
            return r
        except requests.RequestException as e:
            last = e
            time.sleep(sleep * (2 ** i))
    raise last or RuntimeError("request failed")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_date(d) -> str:
    if isinstance(d, datetime):
        return d.date().isoformat()
    if isinstance(d, date):
        return d.isoformat()
    return str(d)[:10]


def parse_date(s) -> Optional[date]:
    if not s:
        return None
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, date):
        return s
    s = str(s).strip()
    for fmt, n in (("%Y-%m-%d", 10), ("%Y/%m/%d", 10), ("%Y-%m", 7), ("%Y", 4)):
        try:
            return datetime.strptime(s[:n], fmt).date()
        except ValueError:
            continue
    try:
        from dateutil import parser
        return parser.parse(s).date()
    except Exception:
        return None


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def redact(text: str, secrets) -> str:
    for name in SECRET_ENV_NAMES:
        v = secrets.get(name)
        if v and v in text:
            text = text.replace(v, f"<{name}>")
    return text
