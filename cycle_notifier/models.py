"""Core immutable data models shared by every module."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

Flow = Literal["light", "medium", "heavy", "unspecified", "spotting"]
Confidence = Literal["high", "medium", "low", "default"]
Status = Literal["upcoming", "in_period", "late", "stale", "no_data"]


@dataclass(frozen=True)
class Period:
    """A menstrual period. ``end`` is inclusive and may be ``None`` if ongoing."""

    start: date
    end: date | None = None
    sources: frozenset[str] = frozenset()
    manual: bool = False
    end_estimated: bool = False
    note: str | None = None

    def days(self) -> int | None:
        """Length in days (inclusive), or None when the end is unknown."""
        return None if self.end is None else (self.end - self.start).days + 1


@dataclass(frozen=True)
class FlowDay:
    """A single day with observed bleeding."""

    day: date
    source: str
    flow: Flow | None = None


@dataclass(frozen=True)
class SourceResult:
    """Outcome of reading a source. Adapters never raise: errors live here."""

    source: str
    periods: tuple[Period, ...] = ()
    flow_days: tuple[FlowDay, ...] = ()
    warnings: tuple[str, ...] = ()
    error: str | None = None
    skipped: bool = False  # source not configured: neither success nor failure


@dataclass(frozen=True)
class Prediction:
    """Prediction of the next period."""

    anchor: date | None
    start: date | None
    end: date | None
    avg_cycle: float
    avg_duration: int
    sd_cycle: float | None
    n_cycles: int
    confidence: Confidence
    status: Status
    days_until: int | None
    window: tuple[date, date] | None = None

    @property
    def has_data(self) -> bool:
        return self.status != "no_data"


@dataclass(frozen=True)
class Contact:
    """Someone who may receive reminders (only with explicit consent)."""

    id: str
    name: str
    email: str = ""
    lang: str = "it"
    channels: tuple[str, ...] = ("email",)
    offsets_days: tuple[int, ...] | None = None
    consent_given: bool = False
    active: bool = True
    consent_date: str | None = None
    consent_method: str | None = None

    @property
    def can_receive(self) -> bool:
        return self.consent_given and self.active


@dataclass(frozen=True)
class Notification:
    """A reminder that should be sent now."""

    contact: Contact
    offset: int
    channel: str
    key: str
    prediction: Prediction = field(compare=False)
