import asyncio
import json

import pytest

from cycle_notifier import mcp_server as m

from .conftest import CONTACTS_JSON


@pytest.fixture(autouse=True)
def home(seeded_home, monkeypatch):
    monkeypatch.setenv("CYCLE_NOTIFIER_HOME", str(seeded_home))
    monkeypatch.setenv("CONTACTS_JSON", CONTACTS_JSON)
    monkeypatch.setenv("FEED_MODE", "none")
    for key in ("SMTP_HOST", "SMTP_FROM", "CYCLES_KEY"):
        monkeypatch.delenv(key, raising=False)
    return seeded_home


def test_tools_are_registered():
    names = {t.name for t in asyncio.run(m.mcp.list_tools())}
    assert names >= {
        "get_cycle_status",
        "predict_next_period",
        "list_cycles",
        "add_period",
        "sync_sources",
        "list_contacts",
        "add_contact",
        "send_test_notification",
        "preview_message",
    }


def test_status_and_predict():
    status = m.get_cycle_status("2026-11-18")
    assert status["prediction"]["days_until"] == 3
    preds = m.predict_next_period(2, "2026-11-18")
    assert [p["start"] for p in preds] == ["2026-11-21", "2026-12-19"]


def test_list_cycles_limit():
    assert len(m.list_cycles(3)) == 3


def test_contacts_are_masked():
    (c,) = m.list_contacts()
    assert c["email"] == "m***@example.com" and "marco@example.com" not in json.dumps(c)


def test_add_contact_writes_local_file(home, monkeypatch):
    monkeypatch.delenv("CONTACTS_JSON")
    out = m.add_contact("Anna", "anna@example.com", consent=True)
    assert out["id"] == "anna"
    written = json.loads((home / "config" / "contacts.local.json").read_text())
    assert written[0]["email"] == "anna@example.com" and written[0]["consent"]["given"]


def test_add_period_without_git_remote(home):
    out = m.add_period("2026-11-10", "2026-11-12")
    assert out["added"]["start"] == "2026-11-10"
    committed = m.add_period("2026-11-14", commit=True)
    assert "git" in committed and "push" not in committed["git"].replace("niente push", "")


def test_sync_sources_dry_run():
    res = m.sync_sources(sources=[], dry_run=True)
    assert res["periods_total"] == 6


def test_preview_and_test_notification_dry_run():
    prev = m.preview_message("marco", 3, "en", "2026-11-18")
    assert prev["subject"].startswith("Reminder") and "BEGIN:VCALENDAR" in prev["ics"]
    out = m.send_test_notification("marco")
    assert out["message_id"] == "dry-run"


def test_status_resource():
    assert json.loads(m.status_resource())["periods_stored"] == 6
