from dataclasses import replace
from datetime import date

from cycle_notifier.config import PredictionSettings
from cycle_notifier.sources.apple_health import AppleHealthAdapter
from cycle_notifier.sources.base import SourceContext

from .conftest import FIXTURES, STARTS, TODAY, FakeSession

XML = FIXTURES / "apple_health" / "export.xml"


def test_parse_xml(ctx):
    res = AppleHealthAdapter().parse(XML, ctx)
    assert res.error is None
    days = sorted(f.day for f in res.flow_days)
    assert len(days) == 30  # 6 periods x 5 days; "None" value and step counts skipped
    assert days[0] == STARTS[0]
    flows = {f.flow for f in res.flow_days}
    assert flows == {"heavy", "medium", "light"}
    assert date(2026, 9, 10) not in days


def test_parse_zip_streams_export_xml(ctx, apple_zip):
    res = AppleHealthAdapter().parse(apple_zip, ctx)
    assert res.error is None and len(res.flow_days) == 30


def test_intermenstrual_only_with_include_spotting(settings):
    st = replace(settings, prediction=replace(PredictionSettings(), include_spotting=True))
    ctx = SourceContext.create(st, TODAY, http=FakeSession())  # type: ignore[arg-type]
    res = AppleHealthAdapter().parse(XML, ctx)
    spot = [f for f in res.flow_days if f.flow == "spotting"]
    assert [f.day for f in spot] == [date(2026, 10, 10)]


def test_timezone_midnight_boundaries(tmp_path, ctx):
    xml = tmp_path / "export.xml"
    rows = [
        ("2026-10-03 00:30:00 +0200", "Light"),  # 22:30Z on the 2nd -> Rome date is the 3rd
        ("2026-10-05 23:30:00 -0500", "Medium"),  # 04:30Z on the 6th -> Rome 06:30 on the 6th
    ]
    body = "".join(
        f'<Record type="HKCategoryTypeIdentifierMenstrualFlow" startDate="{d}" endDate="{d}" '
        f'value="HKCategoryValueMenstrualFlow{v}"/>'
        for d, v in rows
    )
    xml.write_text(f"<HealthData>{body}</HealthData>")
    res = AppleHealthAdapter().parse(xml, ctx)
    assert [f.day for f in res.flow_days] == [date(2026, 10, 3), date(2026, 10, 6)]


def test_corrupt_files_return_error(tmp_path, ctx):
    bad = tmp_path / "export.xml"
    bad.write_text("<HealthData><Record")
    assert AppleHealthAdapter().parse(bad, ctx).error
    bad_zip = tmp_path / "x.zip"
    bad_zip.write_bytes(b"not a zip")
    assert AppleHealthAdapter().parse(bad_zip, ctx).error
