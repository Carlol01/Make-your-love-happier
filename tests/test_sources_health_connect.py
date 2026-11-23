from datetime import date

from cycle_notifier.sources.health_connect import HealthConnectAdapter

from .conftest import STARTS


def test_zip_with_sqlite(ctx, hc_zip):
    res = HealthConnectAdapter().parse(hc_zip, ctx)
    assert res.error is None
    assert [p.start for p in res.periods] == STARTS
    assert res.periods[0].end == date(2026, 6, 10)


def test_renamed_columns_and_flow_table(ctx, hc_zip_renamed):
    res = HealthConnectAdapter().parse(hc_zip_renamed, ctx)
    assert res.error is None
    assert [p.start for p in res.periods] == [STARTS[-1]]
    assert [(f.day, f.flow) for f in res.flow_days] == [(STARTS[-2], "heavy")]


def test_database_without_menstruation_tables(tmp_path, ctx):
    import sqlite3

    db = tmp_path / "x.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE steps(id INTEGER)")
    con.commit()
    con.close()
    res = HealthConnectAdapter().parse(db, ctx)
    assert res.error is None and not res.periods and res.warnings


def test_corrupt_database_is_an_error_not_an_exception(tmp_path, ctx):
    p = tmp_path / "bad.db"
    p.write_bytes(b"SQLite format 3\x00" + b"\x00" * 10)
    assert HealthConnectAdapter().parse(p, ctx).error


def test_zip_without_database(tmp_path, ctx):
    import zipfile

    z = tmp_path / "e.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("readme.txt", "hi")
    assert HealthConnectAdapter().parse(z, ctx).error


def test_database_is_opened_read_only(ctx, hc_zip, tmp_path):
    before = hc_zip.read_bytes()
    HealthConnectAdapter().parse(hc_zip, ctx)
    assert hc_zip.read_bytes() == before
