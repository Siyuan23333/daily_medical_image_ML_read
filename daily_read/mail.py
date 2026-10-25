from __future__ import annotations
import subprocess
from email.message import EmailMessage
from typing import List, Optional
from .util import log


def send(cfg, subject: str, text: str, html: Optional[str] = None, to: Optional[List[str]] = None) -> bool:
    e = cfg.settings["email"]
    if not e.get("enabled", True):
        log.info("email disabled in settings")
        return False
    recipients = to or e.get("to") or []
    if not recipients or not e.get("from"):
        log.error("email not sent: set DIGEST_EMAIL_TO and DIGEST_EMAIL_FROM in the env file")
        return False
    msg = EmailMessage()
    msg["From"] = e["from"]
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    r = subprocess.run([e.get("sendmail", "/usr/sbin/sendmail"), "-t", "-i"], input=msg.as_bytes(), capture_output=True)
    if r.returncode != 0:
        log.error("sendmail failed: %s", r.stderr.decode(errors="replace")[:300])
        return False
    log.info("email sent: %s", subject)
    return True
