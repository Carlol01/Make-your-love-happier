from datetime import date, timedelta

from cycle_notifier.config import PredictionSettings
from cycle_notifier.merge import merge
from cycle_notifier.models import FlowDay, Period

CFG = PredictionSettings()
TODAY = date(2026, 11, 18)


def flows(start: date, n: int, source="a", flow="medium"):
    return [FlowDay(start + timedelta(days=i), source, flow) for i in range(n)]


def test_dedup_same_period_from_two_sources():
    a = Period(date(2026, 10, 1), date(2026, 10, 5), frozenset({"ics"}))
    b = Period(date(2026, 10, 1), date(2026, 10, 5), frozenset({"clue"}))
    out, _ = merge([a, b], [], CFG, TODAY)
    assert len(out) == 1 and out[0].sources == {"ics", "clue"}


def test_gap_of_one_day_merges_gap_of_three_does_not():
    days = flows(date(2026, 10, 1), 2) + flows(date(2026, 10, 4), 2)  # one missing day
    out, _ = merge([], days, CFG, TODAY)
    assert len(out) == 1 and out[0].end == date(2026, 10, 5)
    days = flows(date(2026, 10, 1), 2) + flows(date(2026, 10, 6), 2)  # three missing days
    out, _ = merge([], days, CFG, TODAY)
    assert len(out) == 2


def test_flow_days_make_period_with_real_end():
    out, _ = merge([], flows(date(2026, 10, 1), 4), CFG, TODAY)
    assert out[0].start == date(2026, 10, 1) and out[0].end == date(2026, 10, 4)
    assert not out[0].end_estimated


def test_missing_end_is_estimated_when_not_ongoing():
    out, _ = merge([Period(date(2026, 10, 1), None, frozenset({"x"}))], [], CFG, TODAY)
    assert out[0].end == date(2026, 10, 5) and out[0].end_estimated


def test_missing_end_current_period_stays_open():
    p = Period(date(2026, 11, 17), None, frozenset({"x"}))
    out, _ = merge([p], [], CFG, TODAY)
    assert out[0].end is None and not out[0].end_estimated


def test_real_flow_days_override_estimated_tail():
    stored = [Period(date(2026, 10, 1), date(2026, 10, 5), frozenset({"x"}), end_estimated=True)]
    out, _ = merge([], flows(date(2026, 10, 1), 3), CFG, TODAY, stored=stored)
    assert out[0].end == date(2026, 10, 3) and not out[0].end_estimated


def test_excluded_days_are_removed_and_split():
    p = Period(date(2026, 10, 1), date(2026, 10, 9), frozenset({"x"}))
    out, _ = merge(
        [p], [], CFG, TODAY, excluded_days=[date(2026, 10, 4), date(2026, 10, 5), date(2026, 10, 6)]
    )
    assert [(o.start, o.end) for o in out] == [
        (date(2026, 10, 1), date(2026, 10, 3)),
        (date(2026, 10, 7), date(2026, 10, 9)),
    ]


def test_manual_wins_over_overlapping_cluster():
    manual = Period(date(2026, 10, 2), date(2026, 10, 4), frozenset({"manual"}), manual=True)
    auto = Period(date(2026, 10, 1), date(2026, 10, 6), frozenset({"ics"}))
    out, _ = merge([manual, auto], [], CFG, TODAY)
    assert len(out) == 1 and out[0].manual and out[0].end == date(2026, 10, 4)


def test_history_survives_when_source_no_longer_reports_it():
    stored = [Period(date(2026, 8, 1), date(2026, 8, 5), frozenset({"ics"}))]
    new = [Period(date(2026, 10, 1), date(2026, 10, 5), frozenset({"ics"}))]
    out, _ = merge(new, [], CFG, TODAY, stored=stored)
    assert [o.start for o in out] == [date(2026, 8, 1), date(2026, 10, 1)]


def test_spotting_filtered_unless_enabled():
    days = flows(date(2026, 10, 1), 3, flow="spotting")
    assert merge([], days, CFG, TODAY)[0] == []
    on = PredictionSettings(include_spotting=True)
    assert len(merge([], days, on, TODAY)[0]) == 1


def test_overlong_cluster_dropped_with_warning():
    out, warnings = merge([], flows(date(2026, 10, 1), 20), CFG, TODAY)
    assert out == [] and warnings


def test_output_sorted():
    a = Period(date(2026, 10, 1), date(2026, 10, 5), frozenset({"x"}))
    b = Period(date(2026, 8, 1), date(2026, 8, 5), frozenset({"x"}))
    out, _ = merge([a, b], [], CFG, TODAY)
    assert out == sorted(out, key=lambda p: p.start)
