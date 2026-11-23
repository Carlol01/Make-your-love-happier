from datetime import date, timedelta

from cycle_notifier.config import PredictionSettings
from cycle_notifier.models import Period
from cycle_notifier.predictor import cycle_lengths, predict, predict_many

from .conftest import period, regular_periods

CFG = PredictionSettings()


def test_regular_cycles_high_confidence():
    p = predict(regular_periods(7, last=date(2026, 10, 24)), CFG, date(2026, 11, 10))
    assert p.start == date(2026, 11, 21)
    assert p.end == date(2026, 11, 25)
    assert p.avg_cycle == 28 and p.avg_duration == 5
    assert p.confidence == "high" and p.status == "upcoming"
    assert p.days_until == 11
    assert p.n_cycles == 6


def test_six_cycles_use_last_six_only():
    periods = [period(date(2025, 1, 1))]
    # older irregular history, then six regular 30-day cycles
    periods.append(period(date(2025, 1, 20)))
    last = date(2025, 3, 1)
    for i in range(7):
        periods.append(period(last + timedelta(days=30 * i)))
    p = predict(periods, CFG, date(2025, 9, 1))
    assert p.avg_cycle == 30 and p.n_cycles == 6 and p.confidence == "high"


def test_irregular_cycles_lower_confidence_and_window():
    starts = [date(2026, 1, 1)]
    for n in (26, 31, 28, 33):
        starts.append(starts[-1] + timedelta(days=n))
    p = predict([period(s) for s in starts], CFG, starts[-1] + timedelta(days=5))
    assert p.confidence == "medium"
    assert p.sd_cycle and p.sd_cycle > 2
    assert p.window[0] < p.start < p.window[1]


def test_outlier_cycle_lengths_are_ignored():
    periods = [
        period(date(2026, 1, 1)),
        period(date(2026, 1, 29)),
        period(date(2026, 4, 20)),
        period(date(2026, 5, 18)),
    ]
    assert cycle_lengths(periods, CFG) == [28, 28]  # the 81-day gap is dropped


def test_defaults_with_single_period():
    p = predict([period(date(2026, 11, 1))], CFG, date(2026, 11, 10))
    assert p.confidence == "default" and p.avg_cycle == 28
    assert p.start == date(2026, 11, 29) and p.avg_duration == 5


def test_no_data():
    p = predict([], CFG, date(2026, 11, 10))
    assert p.status == "no_data" and p.start is None and not p.has_data


def test_two_periods_low_confidence():
    p = predict([period(date(2026, 10, 1)), period(date(2026, 10, 30))], CFG, date(2026, 11, 5))
    assert p.confidence == "low" and p.avg_cycle == 29 and p.sd_cycle is None


def test_status_in_period_late_stale():
    base = regular_periods()
    assert predict(base, CFG, date(2026, 10, 26)).status == "in_period"
    assert predict(base, CFG, date(2026, 11, 25)).status == "late"
    assert predict(base, CFG, date(2026, 12, 25)).status == "stale"  # >56 days since anchor


def test_in_period_with_open_end():
    periods = regular_periods(3)
    periods[-1] = Period(periods[-1].start, None, frozenset({"t"}))
    assert predict(periods, CFG, periods[-1].start + timedelta(days=2)).status == "in_period"


def test_predict_many_chains_cycles():
    out = predict_many(regular_periods(), CFG, date(2026, 11, 10), 3)
    assert [p.start for p in out] == [date(2026, 11, 21), date(2026, 12, 19), date(2027, 1, 16)]
    assert out[1].anchor == date(2026, 11, 21)


def test_predict_many_late_returns_single():
    assert len(predict_many(regular_periods(), CFG, date(2026, 11, 25), 3)) == 1


def test_weighted_mean_favours_recent():
    starts = [date(2026, 1, 1)]
    for n in (26, 26, 30, 30):
        starts.append(starts[-1] + timedelta(days=n))
    periods = [period(s) for s in starts]
    plain = predict(periods, CFG, starts[-1])
    weighted = predict(periods, PredictionSettings(weighted=True), starts[-1])
    assert weighted.avg_cycle > plain.avg_cycle


def test_estimated_end_ignored_for_duration():
    periods = regular_periods(3)
    periods = [Period(p.start, p.end, p.sources, end_estimated=True) for p in periods]
    assert predict(periods, CFG, date(2026, 11, 1)).avg_duration == 5  # default, not measured


def test_status_is_relative_to_injected_today_not_clock():
    a = predict(regular_periods(), CFG, date(2026, 11, 20))
    b = predict(regular_periods(), CFG, date(2026, 11, 21))
    assert a.days_until == 1 and b.days_until == 0
