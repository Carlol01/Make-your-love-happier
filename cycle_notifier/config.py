"""Configuration loading. Precedence: environment > .env > config.toml > defaults."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .models import Contact


class ConfigError(Exception):
    """Raised for invalid or missing configuration (CLI exit code 2)."""


@dataclass(frozen=True)
class PredictionSettings:
    history_cycles: int = 6
    min_cycle_days: int = 21
    max_cycle_days: int = 45
    min_period_days: int = 2
    max_period_days: int = 10
    default_cycle_days: int = 28
    default_period_days: int = 5
    stale_after_factor: float = 2.0
    include_spotting: bool = False
    weighted: bool = False


@dataclass(frozen=True)
class NotificationSettings:
    offsets_days: tuple[int, ...] = (3, 2)
    channels: tuple[str, ...] = ("email",)
    catch_up: bool = False
    min_days_between_same_offset: int = 15
    email_provider: str = "smtp"
    attach_ics: bool = True


@dataclass(frozen=True)
class FeedSettings:
    mode: str = "gist"
    event_title: str = "🌸 Ciclo previsto – {user}"
    events_ahead: int = 2
    reminder_events: bool = True
    alarm_time: str = "09:00"


@dataclass(frozen=True)
class SourceSettings:
    enabled: tuple[str, ...] = ("ics", "imports", "garmin")
    ics_keywords: tuple[str, ...] = ("ciclo", "mestruazioni", "period", "periodo", "🩸")
    date_order: str = "DMY"
    delete_imports_after_ingest: bool = False


@dataclass(frozen=True)
class Settings:
    """Immutable application settings."""

    home: Path
    display_name: str = "Giulia"
    timezone: str = "Europe/Rome"
    default_lang: str = "it"
    prediction: PredictionSettings = field(default_factory=PredictionSettings)
    notifications: NotificationSettings = field(default_factory=NotificationSettings)
    feed: FeedSettings = field(default_factory=FeedSettings)
    sources: SourceSettings = field(default_factory=SourceSettings)
    env: dict[str, str] = field(default_factory=dict, compare=False, repr=False)
    contacts: tuple[Contact, ...] = ()

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def data_dir(self) -> Path:
        return self.home / "data"

    @property
    def imports_dir(self) -> Path:
        return self.data_dir / "imports"

    @property
    def config_dir(self) -> Path:
        return self.home / "config"

    @property
    def templates_dir(self) -> Path:
        return self.config_dir / "templates"

    @property
    def contacts_local_path(self) -> Path:
        return self.config_dir / "contacts.local.json"

    @property
    def feed_mode(self) -> str:
        return self.env.get("FEED_MODE") or self.feed.mode

    @property
    def dry_run_env(self) -> bool:
        return self.env.get("NOTIFY_DRY_RUN", "").strip().lower() in {"1", "true", "yes"}

    def get(self, name: str, default: str | None = None) -> str | None:
        value = self.env.get(name)
        return value if value else default


def parse_env_file(text: str) -> dict[str, str]:
    """Parse a minimal ``KEY=VALUE`` .env file (comments, quotes, ``export``)."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if key:
            out[key] = value
    return out


def find_home(start: Path | None = None) -> Path:
    """Locate the project home: $CYCLE_NOTIFIER_HOME or walk up to pyproject.toml."""
    env_home = os.environ.get("CYCLE_NOTIFIER_HOME")
    if env_home:
        return Path(env_home).expanduser().resolve()
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").exists():
            return candidate
    return here


def _section(cls: type, data: dict[str, Any]) -> Any:
    """Build a dataclass from a dict, ignoring unknown keys and coercing lists."""
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name in data:
            value = data[f.name]
            kwargs[f.name] = tuple(value) if isinstance(value, list) else value
    return cls(**kwargs)


def parse_contacts(raw: str | list[dict[str, Any]]) -> tuple[Contact, ...]:
    """Parse the contacts JSON structure into Contact objects."""
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as exc:
        raise ConfigError(f"CONTACTS_JSON non è JSON valido: {exc}") from exc
    if not isinstance(data, list):
        raise ConfigError("I contatti devono essere una lista JSON.")
    contacts: list[Contact] = []
    for item in data:
        if not isinstance(item, dict) or "id" not in item:
            raise ConfigError("Ogni contatto richiede almeno il campo 'id'.")
        consent = item.get("consent") or {}
        offsets = item.get("offsets_days")
        contacts.append(
            Contact(
                id=str(item["id"]),
                name=str(item.get("name", item["id"])),
                email=str(item.get("email", "")),
                lang=str(item.get("lang", "it")),
                channels=tuple(item.get("channels", ["email"])),
                offsets_days=tuple(int(o) for o in offsets) if offsets else None,
                consent_given=bool(consent.get("given", False)),
                active=bool(item.get("active", True)),
                consent_date=consent.get("date"),
                consent_method=consent.get("method"),
            )
        )
    return tuple(contacts)


def contact_to_json(contact: Contact) -> dict[str, Any]:
    """Serialize a Contact back to the on-disk JSON shape."""
    data: dict[str, Any] = {
        "id": contact.id,
        "name": contact.name,
        "email": contact.email,
        "lang": contact.lang,
        "channels": list(contact.channels),
        "consent": {
            "given": contact.consent_given,
            "date": contact.consent_date,
            "method": contact.consent_method,
        },
        "active": contact.active,
    }
    if contact.offsets_days:
        data["offsets_days"] = list(contact.offsets_days)
    return data


def load_settings(home: Path | None = None, environ: dict[str, str] | None = None) -> Settings:
    """Load settings from config.toml, .env and the environment."""
    home = (home or find_home()).resolve()
    environ = dict(os.environ if environ is None else environ)

    toml_data: dict[str, Any] = {}
    toml_path = home / "config" / "config.toml"
    if toml_path.exists():
        try:
            toml_data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"config.toml non valido: {exc}") from exc

    env: dict[str, str] = {}
    dotenv = home / ".env"
    if dotenv.exists():
        env.update(parse_env_file(dotenv.read_text(encoding="utf-8")))
    env.update({k: v for k, v in environ.items() if v != ""})

    user = toml_data.get("user", {})
    settings = Settings(
        home=home,
        display_name=user.get("display_name", "Giulia"),
        timezone=user.get("timezone", "Europe/Rome"),
        default_lang=user.get("default_lang", "it"),
        prediction=_section(PredictionSettings, toml_data.get("prediction", {})),
        notifications=_section(NotificationSettings, toml_data.get("notifications", {})),
        feed=_section(FeedSettings, toml_data.get("feed", {})),
        sources=_section(SourceSettings, toml_data.get("sources", {})),
        env=env,
    )
    try:
        settings.tz  # noqa: B018 - validates the timezone name
    except Exception as exc:
        raise ConfigError(f"Fuso orario non valido: {settings.timezone}") from exc

    contacts_raw = env.get("CONTACTS_JSON")
    if not contacts_raw and settings.contacts_local_path.exists():
        contacts_raw = settings.contacts_local_path.read_text(encoding="utf-8")
    contacts = parse_contacts(contacts_raw) if contacts_raw else ()
    return replace(settings, contacts=contacts)
