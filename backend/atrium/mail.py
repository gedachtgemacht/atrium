"""Sending email with the standard library. Without SMTP settings, mails go to data/outbox as .eml files."""

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from .config import Settings
from .ids import uuid7

log = logging.getLogger("atrium.mail")


def build(settings: Settings, to: str, subject: str, text: str, unsubscribe: str = "") -> EmailMessage:
    m = EmailMessage()
    m["From"] = settings.smtp_from
    m["To"] = to
    m["Subject"] = subject
    m["Date"] = formatdate(localtime=True)
    m["Message-ID"] = make_msgid(domain=settings.smtp_from.rsplit("@", 1)[-1].strip("> ") or "localhost")
    m["Auto-Submitted"] = "auto-generated"
    if unsubscribe:
        m["List-Unsubscribe"] = f"<{unsubscribe}>"
        m["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    m.set_content(text)
    return m


def _send(settings: Settings, msg: EmailMessage) -> None:
    if not settings.smtp_host:
        out = settings.data_dir / "outbox"
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{uuid7().hex}.eml").write_bytes(bytes(msg))
        return
    ctx = ssl.create_default_context()
    if settings.smtp_security == "ssl":
        server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=ctx, timeout=30)
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
    with server:
        if settings.smtp_security == "starttls":
            server.starttls(context=ctx)
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)


async def send(settings: Settings, msg: EmailMessage) -> bool:
    try:
        await asyncio.to_thread(_send, settings, msg)
        return True
    except Exception:
        log.exception("sending mail failed")
        return False
