"""Resend (https://resend.com) HTTP email delivery."""

from __future__ import annotations

import base64

import requests

from ..config import ConfigError, Settings
from .base import Attachment

API_URL = "https://api.resend.com/emails"


class ResendNotifier:
    def __init__(self, api_key: str, sender: str, session: requests.Session | None = None) -> None:
        self.api_key, self.sender = api_key, sender
        self.session = session or requests.Session()

    @classmethod
    def from_settings(cls, settings: Settings) -> ResendNotifier:
        key, sender = settings.get("RESEND_API_KEY"), settings.get("RESEND_FROM")
        if not key or not sender:
            raise ConfigError("Servono RESEND_API_KEY e RESEND_FROM.")
        return cls(key, sender)

    def payload(
        self,
        to: str,
        subject: str,
        text: str,
        html: str | None,
        attachments: list[Attachment] | None,
    ) -> dict:
        data: dict = {"from": self.sender, "to": [to], "subject": subject, "text": text}
        if html:
            data["html"] = html
        if attachments:
            data["attachments"] = [
                {"filename": a.filename, "content": base64.b64encode(a.content).decode()} for a in attachments
            ]
        return data

    def send(
        self,
        to: str,
        subject: str,
        text: str,
        html: str | None = None,
        attachments: list[Attachment] | None = None,
    ) -> str:
        resp = self.session.post(
            API_URL,
            json=self.payload(to, subject, text, html, attachments),
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30,
        )
        resp.raise_for_status()
        return str(resp.json().get("id", ""))
