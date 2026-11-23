"""Notification channels."""

from __future__ import annotations

from ..config import ConfigError, Settings
from .base import Attachment, Notifier


def make_notifier(settings: Settings) -> Notifier:
    """Build the configured email notifier (``smtp`` or ``resend``)."""
    provider = (settings.get("EMAIL_PROVIDER") or settings.notifications.email_provider).lower()
    if provider == "resend":
        from .resend import ResendNotifier

        return ResendNotifier.from_settings(settings)
    if provider == "smtp":
        from .smtp import SmtpNotifier

        return SmtpNotifier.from_settings(settings)
    raise ConfigError(f"email_provider sconosciuto: {provider}")


__all__ = ["Attachment", "Notifier", "make_notifier"]
