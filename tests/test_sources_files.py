from datetime import date

import pytest

from cycle_notifier.sources.registry import get_adapter

from .conftest import FIXTURES, STARTS


def parse(rel: str, ctx, name: str):
    return get_adapter(name).parse(FIXTURES / rel, ctx)


def starts_of(res):
    return sorted(p.start for p in res.periods)


def test_ios_shortcut(ctx):
    res = parse("shortcut/shortcut-sample.json", ctx, "ios_shortcut")
    assert res.error is None
    assert len(res.flow_days) == 15
    assert min(f.day for f in res.flow_days) == STARTS[-3]
    assert {f.flow for f in res.flow_days} == {"medium"}


def test_ios_shortcut_bad_payload(tmp_path, ctx):
    p = tmp_path / "shortcut-x.json"
    p.write_text('{"nope": 1}')
    assert get_adapter("ios_shortcut").parse(p, ctx).error


def test_clue_new_format(ctx):
    res = parse("clue/new.cluedata", ctx, "clue")
    assert len(res.flow_days) == 31
    assert [f.flow for f in res.flow_days if f.flow == "spotting"] == ["spotting"]
    assert res.flow_days[0].flow == "heavy"


def test_clue_old_format(ctx):
    res = parse("clue/old.cluedata", ctx, "clue")
    assert len(res.flow_days) == 30 and res.error is None


def test_clue_unknown_layout_falls_back_to_tolerant(tmp_path, ctx):
    p = tmp_path / "x.cluedata"
    p.write_text('{"history": [{"start": "2026-10-01", "end": "2026-10-05"}]}')
    res = get_adapter("clue").parse(p, ctx)
    assert starts_of(res) == [date(2026, 10, 1)]


def test_flo_drops_future_period(ctx):
    res = parse("flo/export.json", ctx, "flo")
    assert starts_of(res) == STARTS  # the synthetic 2099 entry is dropped
    assert res.periods[0].end == date(2026, 6, 10)
    assert any("scartate" in w for w in res.warnings)


def test_natural_cycles(ctx):
    res = parse("natural_cycles/nc.csv", ctx, "natural_cycles")
    assert len(res.flow_days) == 30
    assert sum(f.flow == "spotting" for f in res.flow_days) == 6
    assert date(2026, 10, 2) not in {f.day for f in res.flow_days}


def test_stardust_best_effort(ctx):
    res = parse("stardust/stardust.csv", ctx, "stardust")
    assert len(res.flow_days) == 30 and res.error is None


def test_period_tracker_best_effort(ctx):
    res = parse("period_tracker/period_tracker.csv", ctx, "period_tracker_gp")
    assert starts_of(res) == STARTS


def test_generic_csv_iso_and_ddmmyyyy(ctx):
    res = parse("generic/periods.csv", ctx, "generic")
    assert starts_of(res) == STARTS
    assert res.periods[-1].note == "dd/mm"


def test_generic_json_open_ended_last(ctx):
    res = parse("generic/periods.json", ctx, "generic")
    assert starts_of(res) == STARTS
    assert res.periods[-1].end is None


@pytest.mark.parametrize("name", ["clue", "flo", "natural_cycles", "stardust", "generic", "ios_shortcut"])
def test_adapters_never_raise_on_garbage(tmp_path, ctx, name):
    p = tmp_path / "garbage.bin"
    p.write_bytes(b"\x00\xff\xfe garbage \x00")
    res = get_adapter(name).parse(p, ctx)
    assert res.error or not res.periods
