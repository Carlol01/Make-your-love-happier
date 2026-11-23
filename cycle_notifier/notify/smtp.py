"""SMTP email delivery (SSL on 465, STARTTLS otherwise)."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

from ..config import ConfigError, Settings
from .base import Attachment


class SmtpNotifier:
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        sender: str,
        reply_to: str | None = None,
    ) -> None:
        self.host, self.port = host, port
        self.user, self.password = user, password
        self.sender, self.reply_to = sender, reply_to

    @classmethod
    def from_settings(cls, settings: Settings) -> SmtpNotifier:
        host = settings.get("SMTP_HOST")
        sender = settings.get("SMTP_FROM")
        if not host or not sender:
            raise ConfigError("Servono SMTP_HOST e SMTP_FROM per inviare email.")
        return cls(
            host=host,
            port=int(settings.get("SMTP_PORT", "465") or 465),
            user=settings.get("SMTP_USER", "") or "",
            password=settings.get("SMTP_PASSWORD", "") or "",
            sender=sender,
            reply_to=settings.get("SMTP_REPLY_TO"),
        )

    def build(
        self,
        to: str,
        subject: str,
        text: str,
        html: str | None,
        attachments: list[Attachment] | None,
    ) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = to
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=parseaddr(self.sender)[1].split("@")[-1] or None)
        reply = self.reply_to or parseaddr(self.sender)[1]
        if reply:
            msg["Reply-To"] = reply
            msg["List-Unsubscribe"] = f"<mailto:{reply}?subject=STOP>"
        msg.set_content(text)
        if html:
            msg.add_alternative(html, subtype="html")
        for att in attachments or []:
            maintype, _, subtype = att.mime.partition("/")
            subtype = subtype.split(";")[0]
            msg.add_attachment(att.content, maintype=maintype, subtype=subtype, filename=att.filename)
        return msg

    def send(
        self,
        to: str,
        subject: str,
        text: str,
        html: str | None = None,
        attachments: list[Attachment] | None = None,
    ) -> str:
        msg = self.build(to, subject, text, html, attachments)
        ctx = ssl.create_default_context()
        if self.port == 465:
            with smtplib.SMTP_SSL(self.host, self.port, context=ctx, timeout=30) as smtp:
                self._deliver(smtp, msg)
        else:
            with smtplib.SMTP(self.host, self.port, timeout=30) as smtp:
                smtp.starttls(context=ctx)
                self._deliver(smtp, msg)
        return str(msg["Message-ID"])

    def _deliver(self, smtp: smtplib.SMTP, msg: EmailMessage) -> None:
        if self.user:
            smtp.login(self.user, self.password)
        smtp.send_message(msg)
