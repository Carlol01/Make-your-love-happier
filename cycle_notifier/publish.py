"""Publish the ICS feed: secret gist, GitHub Pages path, or local file."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from .config import ConfigError, Settings
from .ics_feed import content_hash
from .storage import atomic_write

GIST_API = "https://api.github.com/gists/{gist_id}"


def gist_payload(ics: bytes) -> dict[str, Any]:
    return {"files": {"cycle.ics": {"content": ics.decode("utf-8")}}}


def feed_path(settings: Settings, mode: str) -> Path:
    """Local path used for ``pages`` and ``none`` modes."""
    if mode == "pages":
        token = settings.get("FEED_TOKEN")
        if not token:
            raise ConfigError("FEED_MODE=pages richiede il secret FEED_TOKEN.")
        return settings.home / "build" / "site" / "f" / token / "cycle.ics"
    return settings.home / "build" / "cycle.ics"


def publish(
    ics: bytes,
    settings: Settings,
    state: dict[str, Any],
    now: datetime,
    session: requests.Session | None = None,
    force: bool = False,
) -> str:
    """Publish ``ics`` and return a short status string. Updates ``state['feed']``."""
    mode = settings.feed_mode
    if mode not in ("gist", "pages", "none"):
        raise ConfigError(f"FEED_MODE sconosciuto: {mode}")
    feed_state = state.setdefault("feed", {"sequence": 0, "last_hash": None, "published_at": None})
    digest = content_hash(ics)
    if mode == "gist":
        if not force and feed_state.get("published_hash") == digest:
            return "gist: invariato"
        token, gist_id = settings.get("GIST_TOKEN"), settings.get("GIST_ID")
        if not token or not gist_id:
            raise ConfigError("FEED_MODE=gist richiede GIST_TOKEN e GIST_ID.")
        http = session or requests.Session()
        resp = http.patch(
            GIST_API.format(gist_id=gist_id),
            json=gist_payload(ics),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        feed_state["published_hash"] = digest
        feed_state["published_at"] = now.isoformat(timespec="seconds")
        return "gist: aggiornato"
    path = feed_path(settings, mode)
    atomic_write(path, ics)
    feed_state["published_hash"] = digest
    feed_state["published_at"] = now.isoformat(timespec="seconds")
    return f"{mode}: scritto"
