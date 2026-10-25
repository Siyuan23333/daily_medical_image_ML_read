from __future__ import annotations
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = Path(os.environ.get("DAILY_READ_ENV", Path.home() / ".daily_read.env"))
SECRET_NAMES = [
    "DEEPSEEK_API_KEY", "GITHUB_TOKEN", "GITHUB_REPO", "SPRINGER_METADATA_API_KEY",
    "SPRINGER_OPEN_ACCESS_API_KEY", "ELSEVIER_API_KEY", "ELSEVIER_INSTTOKEN", "NCBI_API_KEY",
]


def load_env_file(path: Path = ENV_FILE) -> Dict[str, str]:
    """Read KEY=VALUE lines. Values are never logged."""
    out: Dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip().lstrip("export ").strip()
        v = v.strip().strip('"').strip("'")
        if k:
            out[k] = v
    return out


@dataclass
class Secrets:
    values: Dict[str, str] = field(default_factory=dict)

    def get(self, name: str) -> str:
        return os.environ.get(name) or self.values.get(name, "")

    def has(self, name: str) -> bool:
        return bool(self.get(name))


@dataclass
class Config:
    settings: Dict[str, Any]
    journals: List[Dict[str, Any]]
    pubmed_queries: List[Dict[str, Any]]
    keywords: Dict[str, List[str]]
    scope: str
    secrets: Secrets
    root: Path = PROJECT_ROOT

    def path(self, key: str) -> Path:
        p = Path(os.path.expanduser(self.settings["paths"][key]))
        return p if p.is_absolute() else self.root / p

    def prompt(self, name: str) -> str:
        return (self.root / "prompts" / f"{name}.md").read_text()

    @property
    def tz(self):
        from zoneinfo import ZoneInfo
        return ZoneInfo(self.settings.get("timezone", "America/New_York"))

    def journal_by_issn(self) -> Dict[str, Dict[str, Any]]:
        m: Dict[str, Dict[str, Any]] = {}
        for j in self.journals:
            for issn in j.get("issn", []):
                m[issn.upper()] = j
        return m

    def compiled_keywords(self, group: str) -> List["re.Pattern[str]"]:
        return [re.compile(p, re.I) for p in self.keywords.get(group, [])]


def load_config(root: Path = PROJECT_ROOT) -> Config:
    cfg_dir = root / "config"
    settings = yaml.safe_load((cfg_dir / "settings.yaml").read_text())
    journals = yaml.safe_load((cfg_dir / "journals.yaml").read_text())["journals"]
    queries = yaml.safe_load((cfg_dir / "pubmed_queries.yaml").read_text())["queries"]
    keywords = yaml.safe_load((cfg_dir / "keywords.yaml").read_text())
    scope = (cfg_dir / "scope.md").read_text()
    secrets = Secrets(load_env_file())
    _apply_personal_values(settings, secrets)
    return Config(settings, journals, queries, keywords, scope, secrets, root)


def _apply_personal_values(settings: Dict[str, Any], secrets: Secrets) -> None:
    """Personal but non-secret values (contact address, digest recipients) live in the env file,
    so the public code repo holds only placeholders."""
    from . import util
    contact = secrets.get("CONTACT_EMAIL")
    if contact:
        settings.setdefault("fulltext", {})["unpaywall_email"] = contact
        settings["fulltext"]["crossref_mailto"] = contact
        util.CONTACT = contact
    to = secrets.get("DIGEST_EMAIL_TO")
    if to:
        settings.setdefault("email", {})["to"] = [x.strip() for x in to.split(",") if x.strip()]
    sender = secrets.get("DIGEST_EMAIL_FROM")
    if sender:
        settings.setdefault("email", {})["from"] = sender
