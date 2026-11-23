"""MCP server (stdio) exposing cycle-notifier tools via FastMCP.

Run with ``python -m cycle_notifier.mcp_server`` or the ``cycle-notifier-mcp`` script.
The tool functions are plain callables so they can be tested directly.
"""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import service
from .config import Settings, load_settings

mcp = FastMCP("cycle-notifier")


def _settings() -> Settings:
    return load_settings()


def _day(value: str | None, st: Settings) -> date:
    return service.parse_day(value, st)


@mcp.tool()
def get_cycle_status(today: str | None = None) -> dict[str, Any]:
    """Stato attuale: previsione del prossimo ciclo, affidabilità e salute delle sorgenti."""
    st = _settings()
    return service.status(st, _day(today, st))


@mcp.tool()
def predict_next_period(count: int = 3, today: str | None = None) -> list[dict[str, Any]]:
    """Prossime date previste (default 3)."""
    st = _settings()
    return [service.prediction_to_dict(p) for p in service.predict(st, _day(today, st), count)]


@mcp.tool()
def list_cycles(limit: int = 12) -> list[dict[str, Any]]:
    """Ultimi periodi registrati."""
    return service.list_cycles(_settings(), limit)


def _git_commit(st: Settings, message: str) -> str:
    """Commit data/ and push, but only if a remote exists."""

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=st.home, capture_output=True, text=True, check=False)

    if git("rev-parse", "--is-inside-work-tree").returncode != 0:
        return "non è un repository git: nessun commit"
    git("add", "data/")
    if git("commit", "-m", message).returncode != 0:
        return "nulla da committare"
    if git("remote").stdout.strip():
        pushed = git("push").returncode == 0
        return "commit e push eseguiti" if pushed else "commit eseguito, push fallito"
    return "commit eseguito (nessun remote: niente push)"


@mcp.tool()
def add_period(
    start: str, end: str | None = None, note: str | None = None, commit: bool = False
) -> dict[str, Any]:
    """Aggiungi un periodo manualmente (date AAAA-MM-GG). Con commit=True fa commit/push dei dati."""
    st = _settings()
    result = service.add_period(st, start, end, note)
    if commit:
        result["git"] = _git_commit(st, "chore(data): periodo aggiunto manualmente [skip ci]")
    return result


@mcp.tool()
def sync_sources(
    sources: list[str] | None = None, files: list[str] | None = None, dry_run: bool = False
) -> dict[str, Any]:
    """Sincronizza le sorgenti (ics, imports, garmin) o importa file specifici."""
    st = _settings()
    rep = service.sync(
        st, sources=sources, files=[Path(f) for f in files] if files else None, dry_run=dry_run
    )
    return rep.to_dict()


@mcp.tool()
def list_contacts() -> list[dict[str, Any]]:
    """Elenco dei contatti (email mascherate)."""
    return service.contacts_list(_settings())


@mcp.tool()
def add_contact(
    name: str,
    email: str,
    lang: str = "it",
    offsets_days: list[int] | None = None,
    consent: bool = False,
) -> dict[str, Any]:
    """Aggiungi un contatto a config/contacts.local.json. Nessun invio senza consenso."""
    return service.contacts_add(_settings(), name, email, lang, offsets_days, consent)


@mcp.tool()
def send_test_notification(contact_id: str, dry_run: bool = True) -> dict[str, Any]:
    """Invia un'email di prova [TEST] a un contatto (default: dry-run)."""
    return service.send_test(_settings(), contact_id, dry_run=dry_run)


@mcp.tool()
def preview_message(
    contact_id: str | None = None,
    offset: int = 3,
    lang: str | None = None,
    today: str | None = None,
) -> dict[str, str]:
    """Anteprima del promemoria: oggetto, corpo e ICS allegato."""
    st = _settings()
    return service.preview(st, contact_id, offset, lang, _day(today, st))


@mcp.resource("cycle://status")
def status_resource() -> str:
    """Stato corrente in JSON."""
    return json.dumps(get_cycle_status(), ensure_ascii=False, indent=2)


def main() -> None:
    """Run the stdio server."""
    mcp.run()


if __name__ == "__main__":
    main()
