"""Decide which reminders are due and track what was already sent."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

from .config import Settings
from .models import Contact, Notification, Prediction


def make_key(anchor: date, contact_id: str, offset: int, channel: str) -> str:
    return f"{anchor.isoformat()}|{contact_id}|{offset}|{channel}"


def _recently_sent(
    state: dict[str, Any], contact_id: str, offset: int, channel: str, today: date, window: int
) -> bool:
    for entry in state.get("sent", {}).values():
        if (
            entry.get("contact") == contact_id
            and entry.get("offset") == offset
            and entry.get("channel", channel) == channel
        ):
            try:
                sent = datetime.fromisoformat(entry["sent_at"]).date()
            except (KeyError, ValueError):
                continue
            if abs((today - sent).days) < window:
                return True
    return False


def due(
    prediction: Prediction,
    contacts: Iterable[Contact],
    state: dict[str, Any],
    settings: Settings,
    today: date,
) -> list[Notification]:
    """Return notifications to send today (consented, active contacts only)."""
    if prediction.status != "upcoming" or prediction.anchor is None or prediction.days_until is None:
        return []
    cfg = settings.notifications
    sent = state.get("sent", {})
    out: list[Notification] = []
    for contact in contacts:
        if not contact.can_receive:
            continue
        offsets = sorted(contact.offsets_days or cfg.offsets_days, reverse=True)
        channels = contact.channels or cfg.channels
        for channel in channels:
            pending: list[int] = []
            # Catch-up only fills a gap: never when this cycle already got a reminder.
            notified = any(make_key(prediction.anchor, contact.id, o, channel) in sent for o in offsets)
            for off in offsets:
                key = make_key(prediction.anchor, contact.id, off, channel)
                if key in sent:
                    continue
                if prediction.days_until == off or (
                    cfg.catch_up and not notified and 0 <= prediction.days_until < off
                ):
                    pending.append(off)
            if not pending:
                continue
            # Exact hit wins; for catch-up send only the smallest unsent offset.
            exact = [o for o in pending if o == prediction.days_until]
            off = exact[0] if exact else min(pending)
            if _recently_sent(state, contact.id, off, channel, today, cfg.min_days_between_same_offset):
                continue
            out.append(
                Notification(
                    contact=contact,
                    offset=off,
                    channel=channel,
                    key=make_key(prediction.anchor, contact.id, off, channel),
                    prediction=prediction,
                )
            )
    return out


def mark_sent(state: dict[str, Any], notification: Notification, now: datetime) -> dict[str, Any]:
    """Record a sent notification in ``state`` (contact ids only, never emails)."""
    pred = notification.prediction
    state.setdefault("sent", {})[notification.key] = {
        "sent_at": now.isoformat(timespec="seconds"),
        "predicted_start": pred.start.isoformat() if pred.start else None,
        "contact": notification.contact.id,
        "offset": notification.offset,
        "channel": notification.channel,
    }
    return state
