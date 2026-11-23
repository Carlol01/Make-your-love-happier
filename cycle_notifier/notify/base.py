"""Notifier protocol and a dry-run implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Attachment:
    filename: str
    content: bytes
    mime: str = "text/calendar; method=PUBLISH"


class Notifier(Protocol):
    """Anything able to deliver a message; returns a provider message id."""

    def send(
        self,
        to: str,
        subject: str,
        text: str,
        html: str | None = None,
        attachments: list[Attachment] | None = None,
    ) -> str: ...


class DryRunNotifier:
    """Records messages instead of sending them (used for ``--dry-run``)."""

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    def send(
        self,
        to: str,
        subject: str,
        text: str,
        html: str | None = None,
        attachments: list[Attachment] | None = None,
    ) -> str:
        self.sent.append({"to": to, "subject": subject})
        return "dry-run"
