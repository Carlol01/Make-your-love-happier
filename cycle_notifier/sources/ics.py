"""ICS calendar source: secret ICS_URLS (remote) or local ``.ics`` files."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from icalendar import Calendar

from ..models import FlowDay, Period, SourceResult
from .base import SourceContext

OWN_UID_SUFFIX = "@cycle-notifier"


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


def keyword_matcher(keywords: tuple[str, ...]) -> re.Pattern[str]:
    """Case/accent-insensitive matcher; word boundaries for alphanumeric keywords."""
    parts = []
    for kw in keywords:
        norm = re.escape(strip_accents(kw.strip()))
        if not norm:
            continue
        parts.append(rf"(?<!\w){norm}(?!\w)" if re.match(r"\w", strip_accents(kw)) else norm)
    return re.compile("|".join(parts) if parts else r"(?!x)x")


def _to_local(value: date | datetime, ctx: SourceContext) -> date:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(ctx.tz).date()
        return value.date()
    return value


def parse_ics_bytes(data: bytes, name: str, ctx: SourceContext) -> SourceResult:
    """Extract periods/flow days from ICS bytes."""
    try:
        cal = Calendar.from_ical(data)
    except Exception as exc:
        return SourceResult("ics", error=f"ICS non valido ({name}): {exc}")
    matcher = keyword_matcher(ctx.settings.sources.ics_keywords)
    periods: list[Period] = []
    flows: list[FlowDay] = []
    warnings: list[str] = []
    rrule_seen = False
    for ev in cal.walk("VEVENT"):
        uid = str(ev.get("UID", ""))
        if uid.endswith(OWN_UID_SUFFIX):
            continue  # our own published feed: avoid a feedback loop
        summary = str(ev.get("SUMMARY", ""))
        if not matcher.search(strip_accents(summary)):
            continue
        dtstart = ev.get("DTSTART")
        if dtstart is None:
            continue
        start = _to_local(dtstart.dt, ctx)
        dtend = ev.get("DTEND")
        if dtend is None:
            end = start
        else:
            raw_end = dtend.dt
            end = _to_local(raw_end, ctx)
            if not isinstance(raw_end, datetime) or (raw_end.hour == raw_end.minute == 0 and end > start):
                end -= timedelta(days=1)  # all-day DTEND is exclusive
        if end < start:
            end = start
        if ev.get("RRULE") is not None:
            rrule_seen = True
        if end == start:
            flows.append(FlowDay(start, "ics", "unspecified"))
        else:
            periods.append(Period(start, end, frozenset({"ics"})))
    if rrule_seen:
        warnings.append("Eventi ricorrenti (RRULE) non espansi: conta solo la prima occorrenza.")
    return SourceResult("ics", tuple(periods), tuple(flows), tuple(warnings))


def _combine(results: list[SourceResult], errors: list[str]) -> SourceResult:
    """Merge several calendars; partial failures become warnings."""
    return SourceResult(
        "ics",
        tuple(p for r in results for p in r.periods),
        tuple(f for r in results for f in r.flow_days),
        tuple(w for r in results for w in r.warnings) + tuple(errors),
    )


class IcsAdapter:
    name = "ics"
    kind = "remote"

    def detect(self, path: Path, head: bytes) -> float:
        if path.suffix.lower() == ".ics" or b"BEGIN:VCALENDAR" in head[:2048]:
            return 0.95
        return 0.0

    def parse(self, path: Path, ctx: SourceContext) -> SourceResult:
        try:
            return parse_ics_bytes(path.read_bytes(), path.name, ctx)
        except OSError as exc:
            return SourceResult("ics", error=f"Impossibile leggere {path.name}: {exc}")

    def fetch(self, ctx: SourceContext) -> SourceResult:
        raw = ctx.settings.get("ICS_URLS")
        if not raw:
            return SourceResult("ics", warnings=("ICS_URLS non configurato: saltato.",), skipped=True)
        results: list[SourceResult] = []
        errors: list[str] = []
        for i, line in enumerate(x.strip() for x in raw.splitlines()):
            if not line or line.startswith("#"):
                continue
            label = f"calendario {i + 1}"  # never log the (secret) URL
            if line.lower().startswith("webcal://"):
                line = "https://" + line[len("webcal://") :]
            try:
                if line.lower().startswith(("http://", "https://")):
                    resp = ctx.http.get(line, timeout=30)
                    resp.raise_for_status()
                    data = resp.content
                else:
                    data = Path(line).read_bytes()
                res = parse_ics_bytes(data, label, ctx)
                if res.error:
                    errors.append(res.error)
                else:
                    results.append(res)
            except (requests.RequestException, OSError) as exc:
                errors.append(f"{label}: {type(exc).__name__}")
        if errors and not results:
            return SourceResult("ics", error="; ".join(errors))
        return _combine(results, errors)
