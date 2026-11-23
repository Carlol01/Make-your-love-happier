import pytest

from cycle_notifier.sources.registry import autodetect, get_adapter, read_head

from .conftest import copy_fixture

CASES = [
    ("ics/sample.ics", "ics"),
    ("apple_health/export.xml", "apple_health"),
    ("shortcut/shortcut-sample.json", "ios_shortcut"),
    ("garmin/calendar.json", "garmin"),
    ("clue/new.cluedata", "clue"),
    ("clue/old.cluedata", "clue"),
    ("flo/export.json", "flo"),
    ("natural_cycles/nc.csv", "natural_cycles"),
    ("stardust/stardust.csv", "stardust"),
    ("period_tracker/period_tracker.csv", "period_tracker_gp"),
    ("generic/periods.csv", "generic"),
    ("generic/periods.json", "generic"),
]


@pytest.mark.parametrize(("rel", "expected"), CASES)
def test_autodetect_fixtures(tmp_path, rel, expected):
    path = copy_fixture(rel, tmp_path)
    assert autodetect(path).name == expected


def test_autodetect_zips(apple_zip, hc_zip):
    assert autodetect(apple_zip).name == "apple_health"
    assert autodetect(hc_zip).name == "health_connect"


def test_unknown_file_falls_back_to_tolerant(tmp_path):
    path = tmp_path / "mystery.csv"
    path.write_text("a,b\n1,2\n")
    assert autodetect(path).name == "tolerant"


def test_zip_head_lists_names_without_extracting(apple_zip):
    head = read_head(apple_zip)
    assert b"apple_health_export/export.xml" in head


def test_get_adapter_names():
    for name in ("ics", "garmin", "clue", "tolerant"):
        assert get_adapter(name).name == name
    with pytest.raises(KeyError):
        get_adapter("nope")
