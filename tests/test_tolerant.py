import json
from dataclasses import replace
from datetime import date

from cycle_notifier.config import SourceSettings
from cycle_notifier.sources._tolerant import TolerantAdapter, parse_date, parse_text
from cycle_notifier.sources.base import SourceContext

from .conftest import TODAY, FakeSession


def make_ctx(settings, order="DMY") -> SourceContext:
    st = replace(settings, sources=replace(SourceSettings(), date_order=order))
    return SourceContext.create(st, TODAY, http=FakeSession())  # type: ignore[arg-type]


def test_parse_date_iso_not_confused_by_dayfirst():
    assert parse_date("2026-10-03", "DMY") == date(2026, 10, 3)
    assert parse_date("2026-10-03T08:00:00+02:00", "DMY") == date(2026, 10, 3)


def test_date_order_dmy_vs_mdy():
    assert parse_date("03/04/2026", "DMY") == date(2026, 4, 3)
    assert parse_date("03/04/2026", "MDY") == date(2026, 3, 4)


def test_epoch_seconds_and_millis():
    assert parse_date(1_790_000_000) == date(2026, 9, 21)
    assert parse_date(1_790_000_000_000) == date(2026, 9, 21)
    assert parse_date("1790000000") == date(2026, 9, 21)


def test_garbage_dates():
    assert parse_date("not a date") is None
    assert parse_date(None) is None and parse_date("") is None


def test_json_walker_nested_unknown_structure(ctx):
    obj = {"export": {"history": [{"periodStart": "2026-10-01", "periodEnd": "2026-10-05"}]}}
    res = parse_text(json.dumps(obj), "x", ctx)
    assert [(p.start, p.end) for p in res.periods] == [(date(2026, 10, 1), date(2026, 10, 5))]


def test_json_walker_day_with_indicator(ctx):
    obj = [
        {"date": "2026-10-01", "period": "heavy"},
        {"date": "2026-10-02", "period": False},
        {"date": "2026-10-03", "mood": "ok"},
    ]
    res = parse_text(json.dumps(obj), "x", ctx)
    assert [(f.day, f.flow) for f in res.flow_days] == [(date(2026, 10, 1), "heavy")]


def test_future_and_ancient_dates_dropped_with_warning(ctx):
    obj = [{"start": "2099-01-01"}, {"start": "1999-12-31"}, {"start": "2026-10-01"}]
    res = parse_text(json.dumps(obj), "x", ctx)
    assert len(res.periods) == 1
    assert any("scartate" in w for w in res.warnings)


def test_csv_aliases_and_semicolons(ctx):
    text = "Inizio;Fine\n01/10/2026;05/10/2026\n29/10/2026;\n"
    res = parse_text(text, "x", ctx)
    assert [(p.start, p.end) for p in res.periods] == [
        (date(2026, 10, 1), date(2026, 10, 5)),
        (date(2026, 10, 29), None),
    ]


def test_csv_dmy_vs_mdy(settings):
    text = "start_date,end_date\n03/04/2026,07/04/2026\n"
    dmy = parse_text(text, "x", make_ctx(settings, "DMY"))
    mdy = parse_text(text, "x", make_ctx(settings, "MDY"))
    assert dmy.periods[0].start == date(2026, 4, 3)
    assert mdy.periods[0].start == date(2026, 3, 4)


def test_csv_day_with_flow_column(ctx):
    text = "date,flow\n2026-10-01,Heavy\n2026-10-02,none\n2026-10-03,spotting\n"
    res = parse_text(text, "x", ctx)
    assert [(f.day.day, f.flow) for f in res.flow_days] == [(1, "heavy"), (3, "spotting")]


def test_invalid_json_returns_error_not_exception(ctx):
    assert parse_text("{broken", "x", ctx).error


def test_unrecognised_content_warns(ctx):
    res = parse_text("foo,bar\n1,2\n", "x", ctx)
    assert not res.periods and res.warnings


def test_adapter_never_raises_on_missing_file(tmp_path, ctx):
    res = TolerantAdapter().parse(tmp_path / "missing.csv", ctx)
    assert res.error
