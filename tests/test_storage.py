import json

import pytest
from cryptography.fernet import Fernet

from cycle_notifier.config import ConfigError
from cycle_notifier.storage import StorageError, Store, atomic_write


def test_roundtrip_plain(make_settings):
    st = make_settings()
    store = Store(st)
    data = store.load_cycles()
    assert data["periods"] == [] and data["schema_version"] == 1
    data["periods"].append({"start": "2026-10-01", "end": "2026-10-05"})
    store.save_cycles(data)
    assert store.load_cycles()["periods"][0]["start"] == "2026-10-01"
    assert (st.data_dir / "cycles.json").exists()


def test_atomic_write_leaves_no_temp_files(tmp_path):
    atomic_write(tmp_path / "a.json", b"{}")
    atomic_write(tmp_path / "a.json", b'{"x":1}')
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]
    assert json.loads((tmp_path / "a.json").read_text()) == {"x": 1}


def test_atomic_write_failure_keeps_old_file(tmp_path, monkeypatch):
    target = tmp_path / "a.json"
    atomic_write(target, b"old")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("os.replace", boom)
    with pytest.raises(OSError):
        atomic_write(target, b"new")
    assert target.read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]


def test_periods_sorted_on_save(make_settings):
    store = Store(make_settings())
    data = store.load_cycles()
    data["periods"] = [{"start": "2026-10-01"}, {"start": "2026-08-01"}]
    store.save_cycles(data)
    assert [p["start"] for p in store.load_cycles()["periods"]] == ["2026-08-01", "2026-10-01"]


def test_fernet_roundtrip_and_ciphertext(make_settings):
    key = Fernet.generate_key().decode()
    st = make_settings(CYCLES_KEY=key)
    store = Store(st)
    data = store.load_cycles()
    data["periods"].append({"start": "2026-10-01", "end": None})
    store.save_cycles(data)
    enc = st.data_dir / "cycles.json.enc"
    assert enc.exists() and not (st.data_dir / "cycles.json").exists()
    assert b"2026-10-01" not in enc.read_bytes()
    assert store.load_cycles()["periods"][0]["start"] == "2026-10-01"


def test_refuse_plaintext_save_when_encrypted_file_exists(make_settings):
    key = Fernet.generate_key().decode()
    Store(make_settings(CYCLES_KEY=key)).save_cycles(Store.empty_cycles())
    keyless = Store(make_settings())
    with pytest.raises(StorageError):
        keyless.save_cycles(Store.empty_cycles())
    with pytest.raises(StorageError):
        keyless.load_cycles()


def test_migrate_both_directions(make_settings):
    st_plain = make_settings()
    Store(st_plain).save_cycles(Store.empty_cycles())
    Store(st_plain).save_state(Store.empty_state())
    key = Fernet.generate_key().decode()
    keyed = Store(make_settings(CYCLES_KEY=key))
    assert sorted(keyed.migrate(encrypt=True)) == ["cycles.json.enc", "state.json.enc"]
    assert not (st_plain.data_dir / "cycles.json").exists()
    assert sorted(keyed.migrate(encrypt=False)) == ["cycles.json", "state.json"]


def test_invalid_key(make_settings):
    with pytest.raises(ConfigError):
        Store(make_settings(CYCLES_KEY="not-a-key"))


def test_schema_version_too_new(make_settings):
    st = make_settings()
    st.data_dir.mkdir(parents=True)
    (st.data_dir / "cycles.json").write_text('{"schema_version": 99}')
    with pytest.raises(StorageError):
        Store(st).load_cycles()


def test_state_prunes_old_sent(make_settings):
    from datetime import date

    store = Store(make_settings())
    state = store.load_state()
    state["sent"] = {
        "old": {"sent_at": "2026-01-01T08:00:00"},
        "new": {"sent_at": "2026-11-01T08:00:00"},
    }
    store.save_state(state, today=date(2026, 11, 18))
    assert list(store.load_state()["sent"]) == ["new"]
