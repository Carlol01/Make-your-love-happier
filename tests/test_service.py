import json
from datetime import date

import pytest

from cycle_notifier import service
from cycle_notifier.config import load_settings
from cycle_notifier.service import NoDataError, UserError

from .conftest import CONTACTS_JSON, FIXTURES, TODAY, FakeNotifier, FakeSession, copy_fixture


@pytest.fixture
def home(seeded_home):
    return seeded_home


@pytest.fixture
def st(home):
    return load_settings(home, environ={"CONTACTS_JSON": CONTACTS_JSON, "FEED_MODE": "none"})


def test_sync_file_merges_and_saves(make_settings):
    st = make_settings()
    rep = service.sync(st, TODAY, files=[FIXTURES / "generic" / "periods.csv"])
    assert rep.periods_total == 6
    assert len(service.list_cycles(st)) == 6
    assert st.data_dir.joinpath("cycles.json").exists()


def test_sync_dry_run_writes_nothing(make_settings):
    st = make_settings()
    service.sync(st, TODAY, files=[FIXTURES / "generic" / "periods.csv"], dry_run=True)
    assert not st.data_dir.joinpath("cycles.json").exists()


def test_imports_are_ingested_once(make_settings):
    st = make_settings()
    copy_fixture("clue/new.cluedata", st.imports_dir)
    first = service.sync(st, TODAY, sources=["imports"])
    assert first.sources["clue"]["periods"] == 31 and not first.skipped_imports
    again = service.sync(st, TODAY, sources=["imports"])
    assert again.skipped_imports == ["data/imports/new.cluedata"]
    assert "clue" not in again.sources
    assert service.sync(st, TODAY, sources=["imports"]).periods_total == first.periods_total


def test_imports_deleted_after_ingest_when_configured(make_settings):
    st = make_settings()
    from dataclasses import replace

    from cycle_notifier.config import SourceSettings

    st = replace(st, sources=replace(SourceSettings(), delete_imports_after_ingest=True))
    path = copy_fixture("generic/periods.csv", st.imports_dir)
    service.sync(st, TODAY, sources=["imports"])
    assert not path.exists()


def test_all_sources_failing_without_data_raises(make_settings):
    st = make_settings(ICS_URLS="https://calendar.example.com/x.ics")
    with pytest.raises(NoDataError):
        service.sync(st, TODAY, sources=["ics"], http=FakeSession())  # type: ignore[arg-type]


def test_all_sources_failing_with_stored_data_keeps_history(st):
    st = load_settings(st.home, environ={"ICS_URLS": "https://calendar.example.com/x.ics"})
    rep = service.sync(st, TODAY, sources=["ics"], http=FakeSession())  # type: ignore[arg-type]
    assert rep.periods_total == 6


def test_status_and_predict(st):
    info = service.status(st, TODAY)
    assert info["prediction"]["start"] == "2026-11-21" and info["prediction"]["days_until"] == 3
    assert [p.start.isoformat() for p in service.predict(st, TODAY, 2)] == ["2026-11-21", "2026-12-19"]


def test_add_period_and_validation(st):
    out = service.add_period(st, "2026-11-10", "2026-11-12", note="test", today=TODAY)
    assert out["added"]["start"] == "2026-11-10"
    last = service.list_cycles(st)[-1]
    assert last["manual"] and last["note"] == "test"
    with pytest.raises(UserError):
        service.add_period(st, "2026-12-01", today=TODAY)
    with pytest.raises(UserError):
        service.add_period(st, "2026-11-10", "2026-11-01", today=TODAY)
    with pytest.raises(UserError):
        service.add_period(st, "not-a-date", today=TODAY)


def test_exclude_days_rebuilds_history(st):
    service.exclude_days(st, ["2026-10-24", "2026-10-25", "2026-10-26", "2026-10-27", "2026-10-28"], TODAY)
    assert service.list_cycles(st)[-1]["start"] == "2026-09-26"
    # and the exclusion survives a later sync
    service.sync(st, TODAY, files=[FIXTURES / "generic" / "periods.csv"])
    assert service.list_cycles(st)[-1]["start"] == "2026-09-26"


def test_run_dry_run_sends_nothing_and_writes_no_state(st):
    notifier = FakeNotifier()
    res = service.run(st, TODAY, dry_run=True, notifier=notifier)
    assert res["due"] == 1 and res["sent"] == 1 and res["dry_run"]
    assert notifier.sent == []  # dry-run uses its own recorder
    assert not st.data_dir.joinpath("state.json").exists()


def test_real_run_sends_once_and_dedups(st, monkeypatch, tmp_path):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    notifier = FakeNotifier()
    res = service.run(st, TODAY, notifier=notifier)
    assert res["sent"] == 1 and res["errors"] == []
    (mail,) = notifier.sent
    assert mail["to"] == "marco@example.com"
    assert mail["subject"] == "Promemoria: il ciclo di Giulia è previsto tra 3 giorni"
    assert mail["attachments"][0].filename == "ciclo.ics"
    state = json.loads(st.data_dir.joinpath("state.json").read_text())
    assert list(state["sent"]) == ["2026-10-24|marco|3|email"]
    assert "@" not in json.dumps(state)  # contact ids only
    assert state["last_prediction"]["start"] == "2026-11-21"
    # second run: nothing new
    again = service.run(st, TODAY, notifier=notifier)
    assert again["due"] == 0 and len(notifier.sent) == 1
    # the next offset (2 days) is due the day after
    nxt = service.run(st, date(2026, 11, 19), notifier=notifier)
    assert nxt["sent"] == 1 and len(notifier.sent) == 2
    text = summary.read_text()
    assert "@" not in text and "2026-11" not in text and "novembre" not in text
    assert (st.home / "build" / "cycle.ics").exists()


def test_failed_send_is_not_marked_sent(st):
    class Failing:
        def send(self, *a, **k):
            raise RuntimeError("smtp down")

    res = service.run(st, TODAY, notifier=Failing())
    assert res["failed"] == 1 and res["errors"]
    state = json.loads(st.data_dir.joinpath("state.json").read_text())
    assert state["sent"] == {}
    ok = FakeNotifier()
    assert service.run(st, TODAY, notifier=ok)["sent"] == 1  # retried next time


def test_no_notification_without_consent(home):
    contacts = json.dumps([{"id": "x", "name": "X", "email": "x@example.com"}])
    st = load_settings(home, environ={"CONTACTS_JSON": contacts, "FEED_MODE": "none"})
    n = FakeNotifier()
    assert service.run(st, TODAY, notifier=n)["due"] == 0


def test_env_dry_run(home):
    st = load_settings(
        home, environ={"CONTACTS_JSON": CONTACTS_JSON, "FEED_MODE": "none", "NOTIFY_DRY_RUN": "1"}
    )
    n = FakeNotifier()
    res = service.run(st, TODAY, notifier=n)
    assert res["dry_run"] and n.sent == []


def test_preview_with_and_without_data(st, make_settings):
    out = service.preview(st, "marco", 3, "it", TODAY)
    assert "sabato 21 novembre" in out["body"] and "BEGIN:VCALENDAR" in out["ics"]
    empty = service.preview(make_settings(), None, 2, "en", TODAY)
    assert "Reminder" in empty["subject"] and "in 2 days" in empty["subject"]


def test_unknown_contact(st):
    with pytest.raises(UserError):
        service.preview(st, "nobody", 3, None, TODAY)


def test_test_and_invite_allowed_without_consent(home):
    contacts = json.dumps([{"id": "x", "name": "X", "email": "x@example.com"}])
    st = load_settings(home, environ={"CONTACTS_JSON": contacts})
    n = FakeNotifier()
    out = service.send_test(st, "x", TODAY, notifier=n)
    assert out["subject"].startswith("[TEST]") and n.sent[0]["to"] == "x@example.com"
    inv = service.invite(st, "x", TODAY, notifier=n)
    assert "promemoria" in inv["subject"].lower() and "sì" in n.sent[1]["text"]
    assert service.send_test(st, "x", TODAY, dry_run=True)["message_id"] == "dry-run"


def test_contacts_add_and_mask(make_settings):
    st = make_settings()
    out = service.contacts_add(st, "Marco Rossi", "marco@example.com", consent=True, today=TODAY)
    assert out["id"] == "marco-rossi" and "gh secret set CONTACTS_JSON" in out["hint"]
    again = service.contacts_add(st, "Marco Rossi", "marco2@example.com", today=TODAY)
    assert again["id"] == "marco-rossi-2" and again["warning"]
    st2 = load_settings(st.home, environ={})
    listed = service.contacts_list(st2)
    assert listed[0]["email"] == "m***@example.com" and listed[0]["consent"] is True
    assert listed[1]["consent"] is False
    with pytest.raises(UserError):
        service.contacts_add(st, "X", "not-an-email")


def test_ingest_dispatch(make_settings, tmp_path):
    st = make_settings()
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {
                "action": "cycle-data",
                "client_payload": {"samples": [{"start": "2026-10-24", "end": "2026-10-28"}]},
            }
        )
    )
    out = service.ingest_dispatch(st, event)
    assert out.parent == st.imports_dir and out.name.startswith("shortcut-")
    assert json.loads(out.read_text())["source"] == "ios_shortcut"
    res = service.sync(st, TODAY, sources=["imports"])
    assert res.sources["ios_shortcut"]["error"] is None
    bad = tmp_path / "bad.json"
    bad.write_text('{"client_payload": {}}')
    with pytest.raises(UserError):
        service.ingest_dispatch(st, bad)


def test_mask_email():
    assert service.mask_email("marco@example.org") == "m***@example.org"
    assert service.mask_email("nonsense") == "***"
