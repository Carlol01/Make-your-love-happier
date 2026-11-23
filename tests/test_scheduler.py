from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from cycle_notifier.config import NotificationSettings
from cycle_notifier.models import Contact
from cycle_notifier.predictor import predict
from cycle_notifier.scheduler import due, mark_sent

from .conftest import regular_periods

NOW = datetime(2026, 11, 18, 8, 0)


def pred_for(today: date):
    return predict(
        regular_periods(7), __import__("cycle_notifier.config", fromlist=["x"]).PredictionSettings(), today
    )


@pytest.fixture
def state():
    return {"sent": {}}


@pytest.mark.parametrize(
    "today,expected",
    [
        (date(2026, 11, 18), [3]),
        (date(2026, 11, 19), [2]),
        (date(2026, 11, 17), []),
        (date(2026, 11, 20), []),
        (date(2026, 11, 21), []),
    ],
)
def test_due_only_on_offsets(settings, marco, state, today, expected):
    got = [n.offset for n in due(pred_for(today), [marco], state, settings, today)]
    assert got == expected


def test_dedup_by_key(settings, marco, state):
    today = date(2026, 11, 18)
    pred = pred_for(today)
    (n,) = due(pred, [marco], state, settings, today)
    mark_sent(state, n, NOW)
    assert due(pred, [marco], state, settings, today) == []
    assert n.key == "2026-10-24|marco|3|email"
    assert state["sent"][n.key]["contact"] == "marco"
    assert "email" not in {k for k in state["sent"][n.key] if "@" in str(state["sent"][n.key][k])}


def test_min_days_between_same_offset_window(settings, marco, state):
    today = date(2026, 11, 18)
    state["sent"]["2026-09-26|marco|3|email"] = {
        "sent_at": (NOW - timedelta(days=10)).isoformat(),
        "contact": "marco",
        "offset": 3,
        "channel": "email",
    }
    assert due(pred_for(today), [marco], state, settings, today) == []
    state["sent"]["2026-09-26|marco|3|email"]["sent_at"] = (NOW - timedelta(days=28)).isoformat()
    assert len(due(pred_for(today), [marco], state, settings, today)) == 1


def test_catch_up_sends_smallest_unsent_offset(settings, marco, state):
    cfg = replace(settings, notifications=NotificationSettings(catch_up=True))
    today = date(2026, 11, 20)  # 1 day before: both offsets were missed
    got = due(pred_for(today), [marco], state, cfg, today)
    assert [n.offset for n in got] == [2]
    mark_sent(state, got[0], NOW)
    tomorrow = date(2026, 11, 21)  # already reminded this cycle: no further catch-up
    assert due(pred_for(tomorrow), [marco], state, cfg, tomorrow) == []


def test_requires_consent_and_active(settings, state, marco):
    today = date(2026, 11, 18)
    pred = pred_for(today)
    no_consent = replace(marco, consent_given=False)
    inactive = replace(marco, active=False)
    assert due(pred, [no_consent, inactive], state, settings, today) == []


def test_late_and_stale_never_notify(settings, marco, state):
    for today in (date(2026, 11, 25), date(2026, 12, 30)):
        assert due(pred_for(today), [marco], state, settings, today) == []


def test_in_period_never_notifies(settings, marco, state):
    today = date(2026, 10, 26)
    assert due(pred_for(today), [marco], state, settings, today) == []


def test_per_contact_offsets(settings, state):
    today = date(2026, 11, 20)  # 1 day before
    c = Contact(id="anna", name="Anna", email="anna@example.com", consent_given=True, offsets_days=(1,))
    got = due(pred_for(today), [c], state, settings, today)
    assert [n.offset for n in got] == [1]


def test_no_data_never_notifies(settings, marco, state):
    from cycle_notifier.config import PredictionSettings

    p = predict([], PredictionSettings(), date(2026, 11, 18))
    assert due(p, [marco], state, settings, date(2026, 11, 18)) == []
