"""Shared fixtures. Everything is synthetic and offline."""

from __future__ import annotations

import json
import shutil
import sqlite3
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from cycle_notifier.config import Settings, load_settings
from cycle_notifier.models import Contact, Period
from cycle_notifier.sources.base import SourceContext

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 18)
STARTS = [
    date(2026, 6, 6),
    date(2026, 7, 4),
    date(2026, 8, 1),
    date(2026, 8, 29),
    date(2026, 9, 26),
    date(2026, 10, 24),
]  # 28-day cycles; next expected 2026-11-21


def period(start: date, days: int = 5, **kw) -> Period:
    return Period(start, start + timedelta(days=days - 1), frozenset(kw.pop("sources", {"t"})), **kw)


def regular_periods(n: int = 6, cycle: int = 28, last: date = date(2026, 10, 24)) -> list[Period]:
    return [period(last - timedelta(days=cycle * (n - 1 - i))) for i in range(n)]


class FakeResponse:
    def __init__(self, content: bytes = b"", status: int = 200, json_data=None) -> None:
        self.content = content
        self.status_code = status
        self._json = json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self._json


class FakeSession:
    """Minimal requests.Session stand-in recording calls."""

    def __init__(self, routes: dict[str, FakeResponse] | None = None) -> None:
        self.routes = routes or {}
        self.calls: list[tuple[str, str, dict]] = []

    def _do(self, method: str, url: str, **kw) -> FakeResponse:
        self.calls.append((method, url, kw))
        return self.routes.get(url, FakeResponse(status=404))

    def get(self, url: str, **kw):
        return self._do("GET", url, **kw)

    def post(self, url: str, **kw):
        return self._do("POST", url, **kw)

    def patch(self, url: str, **kw):
        return self._do("PATCH", url, **kw)


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send(self, to, subject, text, html=None, attachments=None) -> str:
        self.sent.append(
            {"to": to, "subject": subject, "text": text, "html": html, "attachments": attachments}
        )
        return f"fake-{len(self.sent)}"


@pytest.fixture
def make_settings(tmp_path):
    def factory(**env: str) -> Settings:
        (tmp_path / "config").mkdir(exist_ok=True)
        return load_settings(tmp_path, environ={k: v for k, v in env.items()})

    return factory


@pytest.fixture
def settings(make_settings) -> Settings:
    return make_settings()


@pytest.fixture
def ctx(settings) -> SourceContext:
    return SourceContext.create(settings, TODAY, http=FakeSession())  # type: ignore[arg-type]


@pytest.fixture
def marco() -> Contact:
    return Contact(
        id="marco",
        name="Marco",
        email="marco@example.com",
        lang="it",
        consent_given=True,
        consent_date="2026-11-20",
        consent_method="email reply",
    )


CONTACTS_JSON = json.dumps(
    [
        {
            "id": "marco",
            "name": "Marco",
            "email": "marco@example.com",
            "lang": "it",
            "channels": ["email"],
            "offsets_days": [3, 2],
            "consent": {"given": True, "date": "2026-11-20", "method": "email reply"},
            "active": True,
        }
    ]
)


@pytest.fixture
def seeded_home(tmp_path):
    """A temp home with data/cycles.json holding the six synthetic periods."""
    (tmp_path / "data" / "imports").mkdir(parents=True)
    (tmp_path / "config").mkdir()
    periods = [
        {
            "start": s.isoformat(),
            "end": (s + timedelta(days=4)).isoformat(),
            "end_estimated": False,
            "sources": ["ics"],
            "manual": False,
            "note": None,
        }
        for s in STARTS
    ]
    (tmp_path / "data" / "cycles.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "updated_at": None,
                "periods": periods,
                "excluded_days": [],
                "source_status": {},
                "ingested_imports": {},
            }
        )
    )
    return tmp_path


@pytest.fixture
def apple_zip(tmp_path) -> Path:
    out = tmp_path / "export.zip"
    with zipfile.ZipFile(out, "w") as zf:
        zf.write(FIXTURES / "apple_health" / "export.xml", "apple_health_export/export.xml")
        zf.writestr("apple_health_export/export_cda.xml", "<ClinicalDocument/>")
    return out


def _epoch_ms(d: date, hour: int = 8, tz_offset_h: int = 2) -> int:
    local = datetime(d.year, d.month, d.day, hour, tzinfo=timezone(timedelta(hours=tz_offset_h)))
    return int(local.timestamp() * 1000)


@pytest.fixture
def hc_zip(tmp_path) -> Path:
    """Health Connect style export: zip containing a SQLite db built from schema.sql."""
    db = tmp_path / "health_connect.db"
    con = sqlite3.connect(db)
    con.executescript((FIXTURES / "health_connect" / "schema.sql").read_text())
    for s in STARTS:
        con.execute(
            "INSERT INTO menstruation_period_record_table(start_time,end_time,start_zone_offset,"
            "end_zone_offset) VALUES (?,?,?,?)",
            (_epoch_ms(s), _epoch_ms(s + timedelta(days=4)), 7200, 7200),
        )
    con.execute("INSERT INTO steps_record_table(start_time,count) VALUES (?,?)", (_epoch_ms(STARTS[0]), 10))
    con.commit()
    con.close()
    out = tmp_path / "Health Connect.zip"
    with zipfile.ZipFile(out, "w") as zf:
        zf.write(db, "health_connect_export.db")
    return out


@pytest.fixture
def hc_zip_renamed(tmp_path) -> Path:
    """Same data with renamed columns, as other Android versions may ship."""
    db = tmp_path / "hc2.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE menstruation_period_record_table (id INTEGER, begin_time INTEGER,
            stop_time INTEGER, zone_offset_begin INTEGER);
        CREATE TABLE menstruation_flow_record_table (id INTEGER, instant INTEGER, flow_type INTEGER);
        """
    )
    con.execute(
        "INSERT INTO menstruation_period_record_table VALUES (1,?,?,7200)",
        (_epoch_ms(STARTS[-1]), _epoch_ms(STARTS[-1] + timedelta(days=4))),
    )
    con.execute("INSERT INTO menstruation_flow_record_table VALUES (1,?,3)", (_epoch_ms(STARTS[-2]),))
    con.commit()
    con.close()
    out = tmp_path / "hc2.zip"
    with zipfile.ZipFile(out, "w") as zf:
        zf.write(db, "export.db")
    return out


def copy_fixture(rel: str, dest_dir: Path, name: str | None = None) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / (name or Path(rel).name)
    shutil.copy(FIXTURES / rel, dest)
    return dest
