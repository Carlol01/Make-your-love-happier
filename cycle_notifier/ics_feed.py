"""Build the calendar feed (ICS) and single-event invites."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from typing import Any

from icalendar import Alarm, Calendar, Event

from .config import Settings
from .i18n import plural_days
from .models import Prediction

UID_SUFFIX = "@cycle-notifier"
_CONF_IT = {
    "high": "alta",
    "medium": "media",
    "low": "bassa",
    "default": "molto bassa (pochi dati)",
}


def _uid(anchor: date | None, index: int, tag: str = "") -> str:
    digest = hashlib.sha256(f"{anchor}+{index}{tag}".encode()).hexdigest()[:16]
    return f"{digest}{UID_SUFFIX}"


def _title(settings: Settings) -> str:
    return settings.feed.event_title.replace("{user}", settings.display_name)


def _description(pred: Prediction) -> str:
    return (
        f"Stima automatica, durata ~{plural_days(pred.avg_duration)}. "
        f"Affidabilità: {_CONF_IT.get(pred.confidence, pred.confidence)}."
    )


def alarm_trigger(offset_days: int, alarm_time: str) -> timedelta:
    """Trigger (negative, relative to the all-day start at 00:00) for ``alarm_time``.

    ``offset_days=3`` and ``09:00`` gives ``-P2DT15H`` (three days before, at 09:00).
    """
    hh, mm = (int(x) for x in alarm_time.split(":"))
    return -timedelta(days=offset_days) + timedelta(hours=hh, minutes=mm)


def _event(
    pred: Prediction,
    index: int,
    settings: Settings,
    now: datetime,
    sequence: int,
    with_alarms: bool,
) -> Event:
    assert pred.start is not None and pred.end is not None
    ev = Event()
    ev.add("uid", _uid(pred.anchor, index))
    ev.add("dtstamp", now)
    ev.add("dtstart", pred.start)
    ev.add("dtend", pred.end + timedelta(days=1))  # all-day DTEND is exclusive
    ev.add("sequence", sequence)
    ev.add("transp", "TRANSPARENT")
    ev.add("class", "PRIVATE")
    ev.add("summary", _title(settings))
    ev.add("description", _description(pred))
    if with_alarms:
        for off in settings.notifications.offsets_days:
            alarm = Alarm()
            alarm.add("action", "DISPLAY")
            alarm.add("description", _title(settings))
            alarm.add(
                "trigger", alarm_trigger(off, settings.feed.alarm_time), parameters={"RELATED": "START"}
            )
            ev.add_component(alarm)
    return ev


def _reminder_event(
    pred: Prediction, index: int, offset: int, settings: Settings, now: datetime, sequence: int
) -> Event:
    assert pred.start is not None
    day = pred.start - timedelta(days=offset)
    ev = Event()
    ev.add("uid", _uid(pred.anchor, index, f"+r{offset}"))
    ev.add("dtstamp", now)
    ev.add("dtstart", day)
    ev.add("dtend", day + timedelta(days=1))
    ev.add("sequence", sequence)
    ev.add("transp", "TRANSPARENT")
    ev.add("class", "PRIVATE")
    ev.add("summary", f"Promemoria: tra {plural_days(offset)} – {settings.display_name}")
    return ev


def _calendar(settings: Settings, method: str = "PUBLISH") -> Calendar:
    cal = Calendar()
    cal.add("prodid", "-//cycle-notifier//IT")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", method)
    cal.add("x-wr-calname", f"Promemoria {settings.display_name}")
    cal.add("x-wr-timezone", settings.timezone)
    cal.add("refresh-interval", timedelta(hours=6), parameters={"VALUE": "DURATION"})
    cal.add("x-published-ttl", "PT6H")
    return cal


def build_feed(
    predictions: list[Prediction],
    settings: Settings,
    state: dict[str, Any],
    today: date | None = None,
    now: datetime | None = None,
) -> bytes:
    """Render the subscription feed.

    ``state["feed"]`` is updated in place: ``sequence`` is bumped only when the
    content (ignoring DTSTAMP/SEQUENCE) changes, tracked through ``last_hash``.
    """
    now = (now or datetime.now(UTC)).astimezone(UTC)
    feed_state = state.setdefault("feed", {"sequence": 0, "last_hash": None, "published_at": None})
    usable = [p for p in predictions if p.start is not None and p.status != "no_data"]
    usable = usable[: max(1, settings.feed.events_ahead)] if usable else []

    def render(sequence: int) -> Calendar:
        cal = _calendar(settings)
        for i, pred in enumerate(usable):
            live = pred.status in ("upcoming", "in_period")
            cal.add_component(_event(pred, i, settings, now, sequence, with_alarms=live))
            if settings.feed.reminder_events and pred.status == "upcoming":
                for off in settings.notifications.offsets_days:
                    assert pred.start is not None
                    if today is not None and pred.start - timedelta(days=off) < today:
                        continue
                    cal.add_component(_reminder_event(pred, i, off, settings, now, sequence))
        return cal

    probe = render(0).to_ical().decode()
    stable = "\n".join(line for line in probe.splitlines() if not line.startswith(("DTSTAMP", "SEQUENCE")))
    digest = "sha256:" + hashlib.sha256(stable.encode()).hexdigest()
    if digest != feed_state.get("last_hash"):
        feed_state["sequence"] = int(feed_state.get("sequence", 0)) + 1
        feed_state["last_hash"] = digest
    return render(int(feed_state["sequence"])).to_ical()


def content_hash(ics: bytes) -> str:
    """Hash of the published feed, ignoring DTSTAMP (used to skip redundant uploads)."""
    lines = [ln for ln in ics.decode("utf-8", "replace").splitlines() if not ln.startswith("DTSTAMP")]
    return "sha256:" + hashlib.sha256("\n".join(lines).encode()).hexdigest()


def build_invite(
    prediction: Prediction,
    settings: Settings,
    now: datetime | None = None,
) -> bytes:
    """Single-event calendar (same UID as the feed's first event) for email attachments."""
    now = (now or datetime.now(UTC)).astimezone(UTC)
    cal = _calendar(settings, method="PUBLISH")
    if prediction.start is not None and prediction.status != "no_data":
        cal.add_component(_event(prediction, 0, settings, now, 0, with_alarms=True))
    return cal.to_ical()
