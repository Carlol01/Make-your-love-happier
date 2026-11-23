"""Atomic JSON persistence with optional Fernet encryption (CYCLES_KEY)."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import ConfigError, Settings
from .models import Period

SCHEMA_VERSION = 1
PRUNE_DAYS = 180


class StorageError(Exception):
    """Raised on unreadable data or forbidden plaintext writes."""


def _fernet(key: str | None):
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:  # pragma: no cover - depends on extras
        raise ConfigError("CYCLES_KEY impostata ma 'cryptography' non è installato.") from exc
    try:
        return Fernet(key.encode())
    except Exception as exc:
        raise ConfigError("CYCLES_KEY non è una chiave Fernet valida.") from exc


def generate_key() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


def atomic_write(path: Path, data: bytes) -> None:
    """Write bytes atomically (temp file + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class Store:
    """Reads and writes ``cycles.json`` and ``state.json`` (plain or encrypted)."""

    def __init__(self, settings: Settings) -> None:
        self.dir = settings.data_dir
        self.key = settings.get("CYCLES_KEY")
        self._fernet = _fernet(self.key)

    # -- low level -----------------------------------------------------
    def _paths(self, name: str) -> tuple[Path, Path]:
        return self.dir / f"{name}.json", self.dir / f"{name}.json.enc"

    def _read(self, name: str, default: dict[str, Any]) -> dict[str, Any]:
        plain, enc = self._paths(name)
        if self._fernet is not None and enc.exists():
            raw = self._fernet.decrypt(enc.read_bytes())
        elif plain.exists():
            raw = plain.read_bytes()
        elif enc.exists():
            raise StorageError(f"{enc.name} è cifrato ma CYCLES_KEY non è impostata.")
        else:
            return dict(default)
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            raise StorageError(f"{name}.json illeggibile: {exc}") from exc
        version = data.get("schema_version", 1)
        if version > SCHEMA_VERSION:
            raise StorageError(f"{name}: schema_version {version} troppo recente.")
        return data

    def _write(self, name: str, data: dict[str, Any]) -> None:
        plain, enc = self._paths(name)
        payload = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False).encode() + b"\n"
        if self._fernet is not None:
            atomic_write(enc, self._fernet.encrypt(payload))
            return
        if enc.exists():
            raise StorageError(
                f"{enc.name} esiste ma CYCLES_KEY non è impostata: rifiuto di scrivere dati in chiaro."
            )
        atomic_write(plain, payload)

    # -- cycles --------------------------------------------------------
    @staticmethod
    def empty_cycles() -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "updated_at": None,
            "periods": [],
            "excluded_days": [],
            "source_status": {},
            "ingested_imports": {},
        }

    def load_cycles(self) -> dict[str, Any]:
        data = self._read("cycles", self.empty_cycles())
        for key, value in self.empty_cycles().items():
            data.setdefault(key, value)
        return data

    def save_cycles(self, data: dict[str, Any], now: datetime | None = None) -> None:
        data["schema_version"] = SCHEMA_VERSION
        data["updated_at"] = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
        data["periods"] = sorted(data["periods"], key=lambda p: p["start"])
        data["excluded_days"] = sorted(set(data["excluded_days"]))
        self._write("cycles", data)

    # -- state ---------------------------------------------------------
    @staticmethod
    def empty_state() -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "last_run": None,
            "last_prediction": None,
            "feed": {"sequence": 0, "last_hash": None, "published_at": None},
            "sent": {},
        }

    def load_state(self) -> dict[str, Any]:
        data = self._read("state", self.empty_state())
        for key, value in self.empty_state().items():
            data.setdefault(key, value)
        return data

    def save_state(self, data: dict[str, Any], today: date | None = None) -> None:
        data["schema_version"] = SCHEMA_VERSION
        if today is not None:
            data["sent"] = prune_sent(data.get("sent", {}), today)
        self._write("state", data)

    # -- migration -----------------------------------------------------
    def migrate(self, encrypt: bool) -> list[str]:
        """Convert stored files to encrypted (``encrypt=True``) or plaintext."""
        changed: list[str] = []
        for name in ("cycles", "state"):
            plain, enc = self._paths(name)
            if encrypt:
                if self._fernet is None:
                    raise ConfigError("Imposta CYCLES_KEY per cifrare.")
                if plain.exists():
                    atomic_write(enc, self._fernet.encrypt(plain.read_bytes()))
                    plain.unlink()
                    changed.append(enc.name)
            elif enc.exists():
                if self._fernet is None:
                    raise ConfigError("Serve CYCLES_KEY per decifrare.")
                atomic_write(plain, self._fernet.decrypt(enc.read_bytes()))
                enc.unlink()
                changed.append(plain.name)
        return changed


def prune_sent(sent: dict[str, Any], today: date) -> dict[str, Any]:
    """Drop ``sent`` entries older than PRUNE_DAYS."""
    cutoff = today - timedelta(days=PRUNE_DAYS)
    out: dict[str, Any] = {}
    for key, entry in sent.items():
        try:
            when = datetime.fromisoformat(entry["sent_at"]).date()
        except (KeyError, ValueError):
            continue
        if when >= cutoff:
            out[key] = entry
    return out


def periods_from_json(items: list[dict[str, Any]]) -> list[Period]:
    """Deserialize stored periods."""
    out: list[Period] = []
    for p in items:
        out.append(
            Period(
                start=date.fromisoformat(p["start"]),
                end=date.fromisoformat(p["end"]) if p.get("end") else None,
                sources=frozenset(p.get("sources", [])),
                manual=bool(p.get("manual", False)),
                end_estimated=bool(p.get("end_estimated", False)),
                note=p.get("note"),
            )
        )
    return sorted(out, key=lambda p: p.start)


def periods_to_json(periods: list[Period]) -> list[dict[str, Any]]:
    """Serialize periods for storage."""
    return [
        {
            "start": p.start.isoformat(),
            "end": p.end.isoformat() if p.end else None,
            "end_estimated": p.end_estimated,
            "sources": sorted(p.sources),
            "manual": p.manual,
            "note": p.note,
        }
        for p in sorted(periods, key=lambda p: p.start)
    ]
