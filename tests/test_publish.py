from datetime import UTC, datetime

import pytest

from cycle_notifier.config import ConfigError
from cycle_notifier.publish import gist_payload, publish

from .conftest import FakeResponse, FakeSession

NOW = datetime(2026, 11, 18, 8, tzinfo=UTC)
ICS = b"BEGIN:VCALENDAR\r\nDTSTAMP:1\r\nEND:VCALENDAR\r\n"
GIST_URL = "https://api.github.com/gists/abc123"


def test_gist_patch_payload_and_headers(make_settings):
    st = make_settings(FEED_MODE="gist", GIST_TOKEN="tok", GIST_ID="abc123")
    session = FakeSession({GIST_URL: FakeResponse(json_data={})})
    state: dict = {}
    assert publish(ICS, st, state, NOW, session) == "gist: aggiornato"  # type: ignore[arg-type]
    method, url, kw = session.calls[0]
    assert method == "PATCH" and url == GIST_URL
    assert kw["json"] == gist_payload(ICS) == {"files": {"cycle.ics": {"content": ICS.decode()}}}
    assert kw["headers"]["Authorization"] == "Bearer tok"
    assert state["feed"]["published_at"]


def test_gist_skipped_when_hash_unchanged(make_settings):
    st = make_settings(FEED_MODE="gist", GIST_TOKEN="tok", GIST_ID="abc123")
    session = FakeSession({GIST_URL: FakeResponse(json_data={})})
    state: dict = {}
    publish(ICS, st, state, NOW, session)  # type: ignore[arg-type]
    same_but_stamp = ICS.replace(b"DTSTAMP:1", b"DTSTAMP:2")
    assert publish(same_but_stamp, st, state, NOW, session) == "gist: invariato"  # type: ignore[arg-type]
    assert len(session.calls) == 1
    changed = ICS.replace(b"END:VCALENDAR", b"X-A:1\r\nEND:VCALENDAR")
    publish(changed, st, state, NOW, session)  # type: ignore[arg-type]
    assert len(session.calls) == 2


def test_gist_requires_credentials(make_settings):
    with pytest.raises(ConfigError):
        publish(ICS, make_settings(FEED_MODE="gist"), {}, NOW, FakeSession())  # type: ignore[arg-type]


def test_pages_path_uses_token(make_settings):
    st = make_settings(FEED_MODE="pages", FEED_TOKEN="s3cr3t")
    publish(ICS, st, {}, NOW)
    assert (st.home / "build" / "site" / "f" / "s3cr3t" / "cycle.ics").read_bytes() == ICS


def test_pages_requires_token(make_settings):
    with pytest.raises(ConfigError):
        publish(ICS, make_settings(FEED_MODE="pages"), {}, NOW)


def test_none_mode_writes_build_file(make_settings):
    st = make_settings(FEED_MODE="none")
    publish(ICS, st, {}, NOW)
    assert (st.home / "build" / "cycle.ics").exists()


def test_unknown_mode(make_settings):
    with pytest.raises(ConfigError):
        publish(ICS, make_settings(FEED_MODE="ftp"), {}, NOW)
