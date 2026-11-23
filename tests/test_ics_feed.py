from dataclasses import replace
from datetime import UTC, date, datetime

from icalendar import Calendar

from cycle_notifier.config import FeedSettings
from cycle_notifier.ics_feed import alarm_trigger, build_feed, build_invite
from cycle_notifier.predictor import predict, predict_many

from .conftest import regular_periods

NOW = datetime(2026, 11, 18, 8, 0, tzinfo=UTC)
TODAY = date(2026, 11, 10)


def preds(today=TODAY, count=2, n=7):
    from cycle_notifier.config import PredictionSettings

    return predict_many(regular_periods(n), PredictionSettings(), today, count)


def parse(data: bytes) -> Calendar:
    return Calendar.from_ical(data)


def events(cal: Calendar):
    return list(cal.walk("VEVENT"))


def test_feed_headers(settings):
    cal = parse(build_feed(preds(), settings, {}, today=TODAY, now=NOW))
    assert str(cal["PRODID"]) == "-//cycle-notifier//IT"
    assert str(cal["VERSION"]) == "2.0" and str(cal["METHOD"]) == "PUBLISH"
    assert str(cal["X-WR-CALNAME"]) == "Promemoria Giulia"
    assert str(cal["X-WR-TIMEZONE"]) == "Europe/Rome"
    assert str(cal["X-PUBLISHED-TTL"]) == "PT6H"
    raw = build_feed(preds(), settings, {}, today=TODAY, now=NOW).decode()
    assert "REFRESH-INTERVAL;VALUE=DURATION:PT6H" in raw


def test_main_events_exclusive_dtend_and_privacy(settings):
    cal = parse(build_feed(preds(), settings, {}, today=TODAY, now=NOW))
    main = [e for e in events(cal) if str(e["SUMMARY"]).startswith("🌸")]
    assert len(main) == 2
    first = main[0]
    assert first["DTSTART"].dt == date(2026, 11, 21)
    assert first["DTEND"].dt == date(2026, 11, 26)  # inclusive end 25th + 1
    assert str(first["CLASS"]) == "PRIVATE" and str(first["TRANSP"]) == "TRANSPARENT"
    assert "Stima automatica, durata ~5 giorni" in str(first["DESCRIPTION"])
    assert str(first["UID"]).endswith("@cycle-notifier")


def test_two_valarms_with_expected_triggers(settings):
    cal = parse(build_feed(preds(), settings, {}, today=TODAY, now=NOW))
    first = [e for e in events(cal) if str(e["SUMMARY"]).startswith("🌸")][0]
    alarms = [c for c in first.subcomponents if c.name == "VALARM"]
    assert len(alarms) == 2
    raw = build_feed(preds(), settings, {}, today=TODAY, now=NOW).decode()
    assert "TRIGGER;RELATED=START:-P2DT15H" in raw
    assert "TRIGGER;RELATED=START:-P1DT15H" in raw
    assert all(str(a["ACTION"]) == "DISPLAY" for a in alarms)


def test_alarm_trigger_math():
    assert alarm_trigger(3, "09:00").total_seconds() == -(2 * 86400 + 15 * 3600)
    assert alarm_trigger(2, "08:30").total_seconds() == -(86400 + 15 * 3600 + 30 * 60)


def test_uids_stable_and_sequence_bumps_only_on_change(settings):
    state: dict = {}
    a = parse(build_feed(preds(), settings, state, today=TODAY, now=NOW))
    seq1 = state["feed"]["sequence"]
    later = datetime(2026, 11, 19, 8, 0, tzinfo=UTC)
    b = parse(build_feed(preds(), settings, state, today=TODAY, now=later))
    assert state["feed"]["sequence"] == seq1  # same content, only DTSTAMP differs
    assert [str(e["UID"]) for e in events(a)] == [str(e["UID"]) for e in events(b)]
    assert all(int(e["SEQUENCE"]) == seq1 for e in events(b))
    # a different prediction changes content -> sequence bump, event UIDs for the main events change anchor
    from cycle_notifier.config import PredictionSettings

    other = predict_many(regular_periods(7, cycle=30), PredictionSettings(), TODAY, 2)
    build_feed(other, settings, state, today=TODAY, now=later)
    assert state["feed"]["sequence"] == seq1 + 1


def test_reminder_events_toggle(settings):
    on = parse(build_feed(preds(), settings, {}, today=TODAY, now=NOW))
    titles = [str(e["SUMMARY"]) for e in events(on)]
    assert any(t.startswith("Promemoria: tra 3 giorni") for t in titles)
    off_settings = replace(settings, feed=replace(FeedSettings(), reminder_events=False))
    off = parse(build_feed(preds(), off_settings, {}, today=TODAY, now=NOW))
    assert not any(str(e["SUMMARY"]).startswith("Promemoria") for e in events(off))


def test_late_prediction_has_no_reminder_events(settings):
    from cycle_notifier.config import PredictionSettings

    late = predict_many(regular_periods(7), PredictionSettings(), date(2026, 11, 25), 2)
    cal = parse(build_feed(late, settings, {}, today=date(2026, 11, 25), now=NOW))
    assert len(events(cal)) == 1


def test_empty_calendar_is_valid(settings):
    from cycle_notifier.config import PredictionSettings

    data = build_feed([predict([], PredictionSettings(), TODAY)], settings, {}, now=NOW)
    cal = parse(data)
    assert events(cal) == [] and str(cal["VERSION"]) == "2.0"


def test_custom_title_is_used(settings):
    custom = replace(settings, feed=replace(FeedSettings(), event_title="Ciclo"))
    cal = parse(build_feed(preds(), custom, {}, today=TODAY, now=NOW))
    assert "Ciclo" in [str(e["SUMMARY"]) for e in events(cal)]


def test_invite_is_single_event_publish_with_same_uid(settings):
    p = preds()
    invite = parse(build_invite(p[0], settings, now=NOW))
    feed = parse(build_feed(p, settings, {}, today=TODAY, now=NOW))
    assert str(invite["METHOD"]) == "PUBLISH"
    assert len(events(invite)) == 1
    assert str(events(invite)[0]["UID"]) == str(events(feed)[0]["UID"])
