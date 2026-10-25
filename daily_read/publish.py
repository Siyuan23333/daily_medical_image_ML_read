from __future__ import annotations
import os
import stat
import subprocess
import time
from pathlib import Path
from typing import List, Optional
import requests
from .util import log


class Publisher:
    """Push generated pages to the gh-pages branch of GITHUB_REPO. Token never touches disk or argv."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.repo = cfg.secrets.get("GITHUB_REPO")
        self.token = cfg.secrets.get("GITHUB_TOKEN")
        self.branch = cfg.settings["publish"].get("branch", "gh-pages")
        self.site = (cfg.root / cfg.settings["publish"].get("site_dir", "site")).resolve()

    @property
    def enabled(self) -> bool:
        return bool(self.repo and self.token and self.cfg.settings["publish"].get("enabled", True))

    def page_url(self, date: str) -> str:
        if not self.repo:
            return ""
        owner, repo = self.repo.split("/", 1)
        return self.cfg.settings["publish"]["pages_url_template"].format(owner=owner.lower(), repo=repo, date=date)  # github.io hosts are lowercase

    # ---- git plumbing ----
    def _git_env(self) -> dict:
        env = dict(os.environ)
        askpass = self.cfg.root / "state" / "git_askpass.sh"
        if not askpass.exists():
            askpass.write_text("#!/bin/sh\ncase \"$1\" in *sername*) echo x-access-token;; *) printf '%s' \"$GH_PUBLISH_TOKEN\";; esac\n")
            askpass.chmod(stat.S_IRWXU)
        env.update({"GIT_ASKPASS": str(askpass), "GIT_TERMINAL_PROMPT": "0", "GH_PUBLISH_TOKEN": self.token,
                    "GIT_AUTHOR_NAME": "DailyRead bot", "GIT_AUTHOR_EMAIL": "dailyread@localhost",
                    "GIT_COMMITTER_NAME": "DailyRead bot", "GIT_COMMITTER_EMAIL": "dailyread@localhost"})
        return env

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=str(self.site), env=self._git_env(), text=True, capture_output=True, check=check)

    def ensure_checkout(self) -> None:
        url = f"https://github.com/{self.repo}.git"
        if not (self.site / ".git").exists():
            self.site.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", "-q", "-b", self.branch], cwd=str(self.site), check=True, capture_output=True)
            self._git("remote", "add", "origin", url)
        r = self._git("fetch", "-q", "origin", self.branch, check=False)
        if r.returncode == 0:
            self._git("checkout", "-q", "-B", self.branch, f"origin/{self.branch}")
        else:
            self._git("checkout", "-q", "-B", self.branch)
        (self.site / ".nojekyll").touch()

    def publish(self, files: List[Path], message: str) -> None:
        self.ensure_checkout()
        for f in files:
            (self.site / f.name).write_bytes(f.read_bytes())
        self._git("add", "-A")
        if self._git("diff", "--cached", "--quiet", check=False).returncode == 0:
            log.info("publish: nothing to commit")
            return
        self._git("commit", "-q", "-m", message)
        r = self._git("push", "-q", "-u", "origin", self.branch, check=False)
        if r.returncode != 0:
            raise RuntimeError("git push failed: " + (r.stderr or r.stdout)[-400:].replace(self.token, "<token>"))
        log.info("publish: pushed %d files", len(files))

    def wait_live(self, url: str, minutes: Optional[int] = None) -> bool:
        minutes = minutes or int(self.cfg.settings["publish"].get("verify_timeout_minutes", 10))
        deadline = time.time() + minutes * 60
        while time.time() < deadline:
            try:
                if requests.get(url, timeout=20).status_code == 200:
                    return True
            except requests.RequestException:
                pass
            time.sleep(20)
        return False
