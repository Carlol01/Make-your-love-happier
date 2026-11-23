import pytest

from cycle_notifier.config import ConfigError, find_home, load_settings, parse_contacts, parse_env_file

from .conftest import CONTACTS_JSON


def test_defaults_without_files(tmp_path):
    st = load_settings(tmp_path, environ={})
    assert st.display_name == "Giulia" and st.timezone == "Europe/Rome"
    assert st.notifications.offsets_days == (3, 2)
    assert st.prediction.default_cycle_days == 28


def test_toml_overrides_defaults(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.toml").write_text(
        '[user]\ndisplay_name = "Anna"\n[notifications]\noffsets_days = [4]\n[feed]\nmode = "pages"\n'
    )
    st = load_settings(tmp_path, environ={})
    assert st.display_name == "Anna" and st.notifications.offsets_days == (4,)
    assert st.feed_mode == "pages"


def test_precedence_env_over_dotenv_over_toml(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.toml").write_text('[feed]\nmode = "pages"\n')
    (tmp_path / ".env").write_text("FEED_MODE=none\nSMTP_HOST=from-dotenv\n")
    st = load_settings(tmp_path, environ={"SMTP_HOST": "from-env"})
    assert st.feed_mode == "none"  # .env beats toml
    assert st.get("SMTP_HOST") == "from-env"  # env beats .env
    st2 = load_settings(tmp_path, environ={"FEED_MODE": "gist"})
    assert st2.feed_mode == "gist"


def test_parse_env_file():
    text = "# c\nA=1\nexport B='two words'\nC=\"x\"\nD=val # comment\n\nbad line\n"
    assert parse_env_file(text) == {"A": "1", "B": "two words", "C": "x", "D": "val"}


def test_contacts_from_env_and_file(tmp_path):
    st = load_settings(tmp_path, environ={"CONTACTS_JSON": CONTACTS_JSON})
    assert st.contacts[0].id == "marco" and st.contacts[0].can_receive
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "contacts.local.json").write_text(CONTACTS_JSON)
    assert load_settings(tmp_path, environ={}).contacts[0].email == "marco@example.com"


def test_invalid_contacts_json():
    with pytest.raises(ConfigError):
        parse_contacts("{not json")
    with pytest.raises(ConfigError):
        parse_contacts('[{"name": "x"}]')


def test_consent_default_false():
    (c,) = parse_contacts('[{"id": "x", "email": "x@example.com"}]')
    assert not c.consent_given and not c.can_receive


def test_invalid_toml_and_timezone(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.toml").write_text("[user\n")
    with pytest.raises(ConfigError):
        load_settings(tmp_path, environ={})
    (tmp_path / "config" / "config.toml").write_text('[user]\ntimezone = "Mars/Base"\n')
    with pytest.raises(ConfigError):
        load_settings(tmp_path, environ={})


def test_find_home_env_and_walk_up(tmp_path, monkeypatch):
    monkeypatch.setenv("CYCLE_NOTIFIER_HOME", str(tmp_path))
    assert find_home() == tmp_path.resolve()
    monkeypatch.delenv("CYCLE_NOTIFIER_HOME")
    (tmp_path / "pyproject.toml").write_text("")
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    assert find_home(sub) == tmp_path.resolve()
