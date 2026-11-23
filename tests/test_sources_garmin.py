import json
from datetime import date

from cycle_notifier.sources.base import SourceContext
from cycle_notifier.sources.garmin import GarminAdapter

from .conftest import FIXTURES, STARTS, TODAY, FakeSession

CALENDAR = json.loads((FIXTURES / "garmin" / "calendar.json").read_text())


class FakeGarmin:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def get_menstrual_calendar_data(self, start: str, end: str):
        self.calls.append((start, end))
        return CALENDAR


class FakeGarminDaily:
    """Client without the calendar endpoint: the adapter falls back to per-day calls."""

    def __init__(self) -> None:
        self.days: list[str] = []

    def get_menstrual_data_for_date(self, day: str):
        self.days.append(day)
        if day in ("2026-11-10", "2026-11-11"):
            return {"periodDay": True, "flow": "medium"}
        return {}


def ctx_with(settings) -> SourceContext:
    return SourceContext.create(settings, TODAY, http=FakeSession())  # type: ignore[arg-type]


def test_fetch_with_fake_client(settings):
    client = FakeGarmin()
    res = GarminAdapter(lambda ctx: client).fetch(ctx_with(settings))
    assert res.error is None
    assert [p.start for p in res.periods] == STARTS
    assert res.periods[0].end == date(2026, 6, 10)  # start + periodLength - 1
    start, end = client.calls[0]
    assert end == "2026-11-18" and start == "2025-11-18"  # last 365 days


def test_fallback_to_daily_endpoint(settings):
    client = FakeGarminDaily()
    res = GarminAdapter(lambda ctx: client).fetch(ctx_with(settings))
    assert res.error is None
    assert sorted(f.day for f in res.flow_days) == [date(2026, 11, 10), date(2026, 11, 11)]
    assert len(client.days) > 100


def test_client_failure_is_reported(settings):
    def boom(ctx):
        raise RuntimeError("login failed")

    res = GarminAdapter(boom).fetch(ctx_with(settings))
    assert res.error and "login failed" in res.error


def test_not_configured_is_skipped_quietly(settings):
    res = GarminAdapter().fetch(ctx_with(settings))
    assert res.error is None and res.warnings and not res.periods


def test_parse_saved_response_file(settings):
    res = GarminAdapter().parse(FIXTURES / "garmin" / "calendar.json", ctx_with(settings))
    assert [p.start for p in res.periods] == STARTS


def test_real_library_is_not_required(settings, monkeypatch):
    """The adapter module must import without garminconnect installed."""
    import sys

    monkeypatch.setitem(sys.modules, "garminconnect", None)
    res = GarminAdapter(lambda ctx: FakeGarmin()).fetch(ctx_with(settings))
    assert res.error is None
