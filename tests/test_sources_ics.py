from datetime import date

import requests

from cycle_notifier.sources.ics import IcsAdapter, keyword_matcher, strip_accents

from .conftest import FIXTURES, FakeResponse, FakeSession

ICS_BYTES = (FIXTURES / "ics" / "sample.ics").read_bytes()


def test_parse_fixture_keywords_accents_boundaries_and_own_uid(ctx):
    res = IcsAdapter().parse(FIXTURES / "ics" / "sample.ics", ctx)
    assert res.error is None
    starts = sorted(p.start for p in res.periods)
    assert starts == [
        date(2026, 6, 6),
        date(2026, 7, 4),
        date(2026, 8, 1),
        date(2026, 8, 29),  # "Mestruazióni" (accent stripped)
        date(2026, 9, 26),  # "PERIODO" (case-insensitive)
    ]
    by_start = {p.start: p for p in res.periods}
    assert by_start[date(2026, 6, 6)].end == date(2026, 6, 10)  # exclusive DTEND -> inclusive
    # single-day timed event becomes a flow day (06:00Z -> local 08:00, same date)
    assert [f.day for f in res.flow_days] == [date(2026, 10, 24)]
    days = {p.start for p in res.periods} | {f.day for f in res.flow_days}
    assert date(2026, 9, 5) not in days  # "Cicloturismo" must not match 'ciclo'
    assert date(2026, 11, 21) not in days  # own @cycle-notifier event skipped
    assert date(2026, 9, 1) not in days  # "Dentista"


def test_keyword_matcher_helpers():
    m = keyword_matcher(("ciclo", "🩸"))
    assert m.search(strip_accents("Il mio Ciclo"))
    assert not m.search("cicloturismo")
    assert m.search("🩸")
    assert strip_accents("Mestruazióni") == "mestruazioni"


def test_timed_event_uses_local_timezone(ctx):
    ics = (
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:x@example.com\r\n"
        b"DTSTART:20261003T223000Z\r\nDTEND:20261003T230000Z\r\nSUMMARY:Ciclo\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    from cycle_notifier.sources.ics import parse_ics_bytes

    res = parse_ics_bytes(ics, "t", ctx)
    assert [f.day for f in res.flow_days] == [date(2026, 10, 4)]  # 22:30Z is already the 4th in Rome


def test_rrule_warns(ctx):
    from cycle_notifier.sources.ics import parse_ics_bytes

    ics = (
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:x@example.com\r\n"
        b"DTSTART;VALUE=DATE:20261003\r\nRRULE:FREQ=MONTHLY\r\nSUMMARY:Ciclo\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    assert any("RRULE" in w for w in parse_ics_bytes(ics, "t", ctx).warnings)


def test_fetch_webcal_is_rewritten_to_https(make_settings):
    from cycle_notifier.sources.base import SourceContext

    st = make_settings(ICS_URLS="webcal://calendar.example.com/secret/basic.ics")
    session = FakeSession({"https://calendar.example.com/secret/basic.ics": FakeResponse(ICS_BYTES)})
    res = IcsAdapter().fetch(SourceContext.create(st, date(2026, 11, 18), session))  # type: ignore[arg-type]
    assert res.error is None and len(res.periods) == 5
    assert session.calls[0][1].startswith("https://")


def test_fetch_http_error_is_reported_without_leaking_url(make_settings):
    from cycle_notifier.sources.base import SourceContext

    url = "https://calendar.example.com/very-secret-token/basic.ics"
    st = make_settings(ICS_URLS=url)
    session = FakeSession({url: FakeResponse(status=500)})
    res = IcsAdapter().fetch(SourceContext.create(st, date(2026, 11, 18), session))  # type: ignore[arg-type]
    assert res.error and "very-secret-token" not in res.error


def test_fetch_connection_error_is_reported(make_settings):
    from cycle_notifier.sources.base import SourceContext

    class Boom(FakeSession):
        def get(self, url, **kw):
            raise requests.ConnectionError("down")

    st = make_settings(ICS_URLS="https://calendar.example.com/x.ics")
    res = IcsAdapter().fetch(SourceContext.create(st, date(2026, 11, 18), Boom()))  # type: ignore[arg-type]
    assert res.error


def test_fetch_local_file_and_partial_failure(make_settings):
    from cycle_notifier.sources.base import SourceContext

    local = FIXTURES / "ics" / "sample.ics"
    st = make_settings(ICS_URLS=f"{local}\nhttps://calendar.example.com/down.ics")
    session = FakeSession({})
    res = IcsAdapter().fetch(SourceContext.create(st, date(2026, 11, 18), session))  # type: ignore[arg-type]
    assert res.error is None and res.periods  # one calendar worked
    assert any("calendario 2" in w for w in res.warnings)


def test_fetch_without_urls_is_skipped(ctx):
    res = IcsAdapter().fetch(ctx)
    assert res.error is None and res.warnings
