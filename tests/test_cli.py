import json

import pytest

from cycle_notifier.cli import main

from .conftest import CONTACTS_JSON


@pytest.fixture
def env(seeded_home, monkeypatch):
    for key in ("SMTP_HOST", "SMTP_FROM", "ICS_URLS", "GARMIN_TOKENS", "GIST_ID", "CYCLES_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CONTACTS_JSON", CONTACTS_JSON)
    monkeypatch.setenv("FEED_MODE", "none")
    monkeypatch.delenv("NOTIFY_DRY_RUN", raising=False)
    monkeypatch.delenv("CYCLE_NOTIFIER_HOME", raising=False)
    return seeded_home


def run(home, *args):
    return main(["--home", str(home), *args])


def test_run_dry_run_end_to_end(env, capsys):
    assert run(env, "run", "--dry-run", "--today", "2026-11-18") == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and "inviati=1" in out
    assert not (env / "data" / "state.json").exists()


def test_predict_text_and_json(env, capsys):
    assert run(env, "predict", "--today", "2026-11-18", "--count", "2") == 0
    assert "sabato 21 novembre" in capsys.readouterr().out
    assert run(env, "predict", "--today", "2026-11-18", "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert data[0]["start"] == "2026-11-21" and len(data) == 3


def test_preview(env, capsys):
    assert run(env, "preview", "--today", "2026-11-18") == 0
    out = capsys.readouterr().out
    assert "Promemoria: il ciclo di Giulia è previsto tra 3 giorni" in out
    assert "Ciao Marco," in out


def test_add_period_and_exclude(env, capsys):
    assert run(env, "add-period", "2026-11-10", "2026-11-12") == 0
    assert run(env, "exclude", "2026-11-11") == 0
    cycles = json.loads((env / "data" / "cycles.json").read_text())
    assert cycles["excluded_days"] == ["2026-11-11"]


def test_sync_file(env, capsys):
    from .conftest import FIXTURES

    assert run(env, "sync", "--file", str(FIXTURES / "generic" / "periods.csv"), "--dry-run") == 0
    assert "dry-run" in capsys.readouterr().out


def test_ics_out(env, tmp_path):
    out = tmp_path / "x.ics"
    assert run(env, "ics", "--out", str(out), "--today", "2026-11-18") == 0
    assert b"BEGIN:VCALENDAR" in out.read_bytes()


def test_ics_new_token(env, capsys):
    assert run(env, "ics", "--new-token") == 0
    assert "FEED_TOKEN" in capsys.readouterr().out


def test_exit_code_2_on_bad_config(env, capsys):
    (env / "config" / "config.toml").write_text("[user\n")
    assert run(env, "predict") == 2
    assert "config.toml" in capsys.readouterr().err


def test_exit_code_2_on_unknown_contact(env, capsys):
    assert run(env, "invite", "nobody", "--dry-run") == 2


def test_exit_code_3_when_all_sources_fail_without_data(tmp_path, monkeypatch, capsys):
    (tmp_path / "config").mkdir()
    monkeypatch.setenv("ICS_URLS", str(tmp_path / "missing.ics"))
    monkeypatch.setenv("FEED_MODE", "none")
    monkeypatch.delenv("CONTACTS_JSON", raising=False)
    monkeypatch.setenv("GARMIN_TOKENS", "")
    assert run(tmp_path, "run", "--dry-run") == 3


def test_ingest_dispatch_cli(env, monkeypatch, tmp_path, capsys):
    event = tmp_path / "e.json"
    event.write_text(json.dumps({"client_payload": {"samples": []}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    assert run(env, "ingest-dispatch") == 0
    assert list((env / "data" / "imports").glob("shortcut-*.json"))


def test_encrypt_decrypt_cli(env, monkeypatch, capsys):
    assert run(env, "encrypt", "--generate-key") == 0
    key = capsys.readouterr().out.strip().split("=", 1)[1]
    monkeypatch.setenv("CYCLES_KEY", key)
    assert run(env, "encrypt") == 0
    assert (env / "data" / "cycles.json.enc").exists()
    assert run(env, "predict", "--today", "2026-11-18") == 0
    assert run(env, "decrypt") == 0
    assert (env / "data" / "cycles.json").exists()
