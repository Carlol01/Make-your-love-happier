"""Application services shared by the CLI and the MCP server."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from . import ics_feed, merge, messages, predictor, publish, scheduler
from .config import ConfigError, Settings, contact_to_json, parse_contacts
from .models import Contact, Period, Prediction, SourceResult
from .notify import Attachment, Notifier, make_notifier
from .notify.base import DryRunNotifier
from .sources import SourceContext, autodetect, get_adapter
from .sources.garmin import ClientFactory, GarminAdapter
from .storage import Store, periods_from_json, periods_to_json


class NoDataError(Exception):
    """All sources failed and there is no stored data (CLI exit code 3)."""


class UserError(Exception):
    """A recoverable user-facing problem (unknown contact, invalid date, ...)."""


def today_local(settings: Settings) -> date:
    """Today's date in the configured timezone."""
    return datetime.now(settings.tz).date()


def parse_day(value: str | date | None, settings: Settings) -> date:
    """Parse an ISO date string (default: today)."""
    if value is None:
        return today_local(settings)
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise UserError(f"Data non valida (usa AAAA-MM-GG): {value}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _rel(settings: Settings, path: Path) -> str:
    try:
        return path.resolve().relative_to(settings.home).as_posix()
    except ValueError:
        return path.name


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------
@dataclass
class SyncReport:
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    periods_total: int = 0
    warnings: list[str] = field(default_factory=list)
    skipped_imports: list[str] = field(default_factory=list)
    merged: list[Period] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sources": self.sources,
            "periods_total": self.periods_total,
            "warnings": self.warnings,
            "skipped_imports": self.skipped_imports,
        }


def _record(report: SyncReport, data: dict[str, Any], res: SourceResult, now: datetime) -> None:
    count = len(res.periods) + len(res.flow_days)
    prev = report.sources.get(res.source, {"periods": 0, "warnings": []})
    entry = {
        "periods": prev["periods"] + count,
        "error": res.error,
        "warnings": [*prev["warnings"], *res.warnings],
    }
    report.sources[res.source] = entry
    data["source_status"][res.source] = {
        "last_sync": now.isoformat(timespec="seconds"),
        "periods": entry["periods"],
        "error": res.error,
    }


def sync(
    settings: Settings,
    today: date | None = None,
    sources: list[str] | None = None,
    files: list[Path] | None = None,
    dry_run: bool = False,
    http: requests.Session | None = None,
    garmin_factory: ClientFactory | None = None,
    store: Store | None = None,
) -> SyncReport:
    """Read sources, merge with stored history and (unless ``dry_run``) save cycles.json."""
    today = today or today_local(settings)
    store = store or Store(settings)
    ctx = SourceContext.create(settings, today, http)
    data = store.load_cycles()
    stored = periods_from_json(data["periods"])
    now = datetime.now(settings.tz)
    report = SyncReport()
    enabled = sources if sources is not None else list(settings.sources.enabled)
    if files and sources is None:
        enabled = []  # explicit files only
    results: list[SourceResult] = []
    ingested = data["ingested_imports"]
    new_hashes: dict[str, str] = {}
    to_delete: list[Path] = []

    for name in enabled:
        if name == "imports":
            imports = (
                sorted(
                    p for p in settings.imports_dir.glob("*") if p.is_file() and not p.name.startswith(".")
                )
                if settings.imports_dir.exists()
                else []
            )
            for path in imports:
                key, digest = _rel(settings, path), _sha256(path)
                if ingested.get(key) == digest:
                    report.skipped_imports.append(key)
                    continue
                res = autodetect(path).parse(path, ctx)
                results.append(res)
                _record(report, data, res, now)
                if res.error is None:
                    new_hashes[key] = digest
                    to_delete.append(path)
            continue
        try:
            adapter = GarminAdapter(garmin_factory) if name == "garmin" else get_adapter(name)
        except KeyError as exc:
            raise UserError(str(exc)) from exc
        res = adapter.fetch(ctx)
        results.append(res)
        _record(report, data, res, now)

    for path in files or []:
        path = Path(path)
        if not path.is_file():
            res = SourceResult("file", error=f"File non trovato: {path.name}")
        else:
            res = autodetect(path).parse(path, ctx)
            if res.error is None:
                new_hashes[_rel(settings, path)] = _sha256(path)
        results.append(res)
        _record(report, data, res, now)

    attempted = [r for r in results if not r.skipped]
    if attempted and all(r.error for r in attempted) and not stored:
        raise NoDataError("Tutte le sorgenti hanno fallito e non ci sono dati salvati.")

    merged, warns = merge.merge(
        [p for r in results for p in r.periods],
        [f for r in results for f in r.flow_days],
        settings.prediction,
        today,
        excluded_days=[date.fromisoformat(d) for d in data["excluded_days"]],
        stored=stored,
    )
    report.warnings = [*warns, *(w for r in results for w in r.warnings)]
    report.periods_total = len(merged)
    report.merged = merged
    if not dry_run:
        data["periods"] = periods_to_json(merged)
        data["ingested_imports"].update(new_hashes)
        store.save_cycles(data, now)
        if settings.sources.delete_imports_after_ingest:
            for path in to_delete:
                path.unlink(missing_ok=True)
    return report


def _remerge(settings: Settings, store: Store, data: dict[str, Any], today: date) -> None:
    merged, _ = merge.merge(
        [],
        [],
        settings.prediction,
        today,
        excluded_days=[date.fromisoformat(d) for d in data["excluded_days"]],
        stored=periods_from_json(data["periods"]),
    )
    data["periods"] = periods_to_json(merged)
    store.save_cycles(data)


# ---------------------------------------------------------------------------
# Queries and manual edits
# ---------------------------------------------------------------------------
def _periods(settings: Settings, store: Store | None = None) -> list[Period]:
    return periods_from_json((store or Store(settings)).load_cycles()["periods"])


def prediction_to_dict(pred: Prediction) -> dict[str, Any]:
    return {
        "status": pred.status,
        "anchor": pred.anchor.isoformat() if pred.anchor else None,
        "start": pred.start.isoformat() if pred.start else None,
        "end": pred.end.isoformat() if pred.end else None,
        "days_until": pred.days_until,
        "confidence": pred.confidence,
        "avg_cycle": round(pred.avg_cycle, 1),
        "avg_duration": pred.avg_duration,
        "sd_cycle": round(pred.sd_cycle, 2) if pred.sd_cycle is not None else None,
        "n_cycles": pred.n_cycles,
        "window": [d.isoformat() for d in pred.window] if pred.window else None,
    }


def predict(settings: Settings, today: date | None = None, count: int = 3) -> list[Prediction]:
    today = today or today_local(settings)
    return predictor.predict_many(_periods(settings), settings.prediction, today, count)


def status(settings: Settings, today: date | None = None) -> dict[str, Any]:
    """Current status (prediction, history size, source health)."""
    today = today or today_local(settings)
    store = Store(settings)
    data = store.load_cycles()
    state = store.load_state()
    pred = predictor.predict(periods_from_json(data["periods"]), settings.prediction, today)
    return {
        "today": today.isoformat(),
        "prediction": prediction_to_dict(pred),
        "periods_stored": len(data["periods"]),
        "source_status": data["source_status"],
        "last_run": state.get("last_run"),
        "contacts": len(settings.contacts),
    }


def list_cycles(settings: Settings, limit: int = 12) -> list[dict[str, Any]]:
    periods = _periods(settings)[-limit:]
    out = []
    for p in periods:
        out.append(
            {
                "start": p.start.isoformat(),
                "end": p.end.isoformat() if p.end else None,
                "days": p.days(),
                "end_estimated": p.end_estimated,
                "sources": sorted(p.sources),
                "manual": p.manual,
                "note": p.note,
            }
        )
    return out


def add_period(
    settings: Settings,
    start: str | date,
    end: str | date | None = None,
    note: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Add (or replace) a manual period; manual entries win over automatic data."""
    today = today or today_local(settings)
    s = parse_day(start, settings)
    e = parse_day(end, settings) if end else None
    if e is not None and e < s:
        raise UserError("La data di fine è precedente all'inizio.")
    if s > today:
        raise UserError("La data di inizio è nel futuro.")
    store = Store(settings)
    data = store.load_cycles()
    kept = [p for p in periods_from_json(data["periods"]) if not (p.manual and p.start == s) and p.start != s]
    kept.append(Period(s, e, frozenset({"manual"}), manual=True, note=note))
    data["periods"] = periods_to_json(kept)
    store.save_cycles(data)
    return {"added": {"start": s.isoformat(), "end": e.isoformat() if e else None}}


def exclude_days(settings: Settings, days: list[str], today: date | None = None) -> dict[str, Any]:
    """Exclude days from the history (e.g. wrongly recorded) and rebuild periods."""
    today = today or today_local(settings)
    parsed = [parse_day(d, settings).isoformat() for d in days]
    store = Store(settings)
    data = store.load_cycles()
    data["excluded_days"] = sorted(set(data["excluded_days"]) | set(parsed))
    _remerge(settings, store, data, today)
    return {"excluded": parsed}


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------
def _find_contact(settings: Settings, contact_id: str) -> Contact:
    for c in settings.contacts:
        if c.id == contact_id:
            return c
    raise UserError(f"Contatto sconosciuto: {contact_id}")


def _sample_contact(lang: str) -> Contact:
    return Contact(id="marco", name="Marco", email="marco@example.com", lang=lang)


def _preview_prediction(settings: Settings, today: date, offset: int) -> Prediction:
    """Prediction used for previews: real if available, else a synthetic example."""
    pred = predictor.predict(_periods(settings), settings.prediction, today)
    if pred.start is not None and pred.status in ("upcoming", "in_period", "late"):
        return replace(pred, days_until=offset)
    start = today + timedelta(days=offset)
    cfg = settings.prediction
    return Prediction(
        anchor=start - timedelta(days=cfg.default_cycle_days),
        start=start,
        end=start + timedelta(days=cfg.default_period_days - 1),
        avg_cycle=float(cfg.default_cycle_days),
        avg_duration=cfg.default_period_days,
        sd_cycle=None,
        n_cycles=0,
        confidence="default",
        status="upcoming",
        days_until=offset,
    )


def preview(
    settings: Settings,
    contact_id: str | None = None,
    offset: int = 3,
    lang: str | None = None,
    today: date | None = None,
) -> dict[str, str]:
    """Render the reminder that would be sent (no sending)."""
    today = today or today_local(settings)
    contact = (
        _find_contact(settings, contact_id) if contact_id else _sample_contact(lang or settings.default_lang)
    )
    pred = _preview_prediction(settings, today, offset)
    msg = messages.render(
        "reminder",
        user=settings.display_name,
        contact=contact,
        prediction=pred,
        n_days=offset,
        lang=lang or contact.lang,
        templates_dir=settings.templates_dir,
    )
    ics = ics_feed.build_invite(pred, settings).decode()
    return {"subject": msg.subject, "body": msg.text, "ics": ics}


def _invite_extra(settings: Settings) -> dict[str, str]:
    feed_url = settings.get("FEED_URL")
    site = (settings.get("SITE_URL") or "https://carlol01.github.io/make-your-love-happier").rstrip("/")
    return {
        "feed_line": f"Calendario (facoltativo): {feed_url}\n" if feed_url else "",
        "guide_url": f"{site}/contatti.html",
    }


def _deliver(
    settings: Settings,
    contact: Contact,
    msg: messages.Message,
    attachments: list[Attachment] | None,
    notifier: Notifier | None,
    dry_run: bool,
) -> str:
    if not contact.email:
        raise UserError(f"Il contatto {contact.id} non ha un indirizzo email.")
    if dry_run:
        return "dry-run"
    notifier = notifier or make_notifier(settings)
    return notifier.send(contact.email, msg.subject, msg.text, msg.html, attachments)


def send_test(
    settings: Settings,
    contact_id: str,
    today: date | None = None,
    dry_run: bool = False,
    notifier: Notifier | None = None,
) -> dict[str, Any]:
    """Send a labelled [TEST] reminder to a single contact (consent not required)."""
    today = today or today_local(settings)
    contact = _find_contact(settings, contact_id)
    pred = _preview_prediction(settings, today, 3)
    msg = messages.render(
        "test",
        user=settings.display_name,
        contact=contact,
        prediction=pred,
        n_days=3,
        templates_dir=settings.templates_dir,
    )
    ident = _deliver(settings, contact, msg, None, notifier, dry_run or settings.dry_run_env)
    return {"contact": contact.id, "subject": msg.subject, "message_id": ident}


def invite(
    settings: Settings,
    contact_id: str,
    today: date | None = None,
    dry_run: bool = False,
    notifier: Notifier | None = None,
) -> dict[str, Any]:
    """Send the consent invitation to a contact (asks them to reply yes/sì)."""
    contact = _find_contact(settings, contact_id)
    msg = messages.render(
        "invite",
        user=settings.display_name,
        contact=contact,
        prediction=None,
        templates_dir=settings.templates_dir,
        extra=_invite_extra(settings),
    )
    ident = _deliver(settings, contact, msg, None, notifier, dry_run or settings.dry_run_env)
    return {"contact": contact.id, "subject": msg.subject, "message_id": ident}


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------
def mask_email(email: str) -> str:
    """``marco@example.com`` -> ``m***@example.com``."""
    if "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def contacts_list(settings: Settings) -> list[dict[str, Any]]:
    return [
        {
            "id": c.id,
            "name": c.name,
            "email": mask_email(c.email),
            "lang": c.lang,
            "channels": list(c.channels),
            "offsets_days": list(c.offsets_days) if c.offsets_days else None,
            "consent": c.consent_given,
            "active": c.active,
        }
        for c in settings.contacts
    ]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "contatto"


def contacts_add(
    settings: Settings,
    name: str,
    email: str,
    lang: str = "it",
    offsets_days: list[int] | None = None,
    consent: bool = False,
    today: date | None = None,
) -> dict[str, Any]:
    """Add a contact to config/contacts.local.json (gitignored)."""
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise UserError("Indirizzo email non valido.")
    today = today or today_local(settings)
    path = settings.contacts_local_path
    existing = parse_contacts(path.read_text(encoding="utf-8")) if path.exists() else ()
    ids = {c.id for c in existing}
    base, cid, n = _slug(name), _slug(name), 2
    while cid in ids:
        cid, n = f"{base}-{n}", n + 1
    contact = Contact(
        id=cid,
        name=name,
        email=email,
        lang=lang,
        offsets_days=tuple(offsets_days) if offsets_days else None,
        consent_given=consent,
        consent_date=today.isoformat() if consent else None,
        consent_method="dichiarato dall'utente" if consent else None,
    )
    payload = [*(contact_to_json(c) for c in existing), contact_to_json(contact)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "id": cid,
        "consent": consent,
        "hint": "Aggiorna il secret: gh secret set CONTACTS_JSON < config/contacts.local.json",
        "warning": None if consent else "Nessun invio finché il consenso non è registrato.",
    }


# ---------------------------------------------------------------------------
# Daily run
# ---------------------------------------------------------------------------
def write_step_summary(lines: list[str]) -> None:
    """Append counts/status (never dates or emails) to $GITHUB_STEP_SUMMARY."""
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def run(
    settings: Settings,
    today: date | None = None,
    dry_run: bool = False,
    do_publish: bool = True,
    notifier: Notifier | None = None,
    http: requests.Session | None = None,
    garmin_factory: ClientFactory | None = None,
) -> dict[str, Any]:
    """Daily pipeline: sync -> predict -> due -> send -> save state -> publish feed."""
    today = today or today_local(settings)
    dry_run = dry_run or settings.dry_run_env
    store = Store(settings)
    report = sync(settings, today, dry_run=dry_run, http=http, garmin_factory=garmin_factory, store=store)
    merged_periods = report.merged
    predictions = predictor.predict_many(
        merged_periods, settings.prediction, today, max(3, settings.feed.events_ahead)
    )
    first = predictions[0]
    state = store.load_state()
    notifications = scheduler.due(first, settings.contacts, state, settings, today)

    sent, failed = 0, 0
    errors: list[str] = []
    dry_notifier = DryRunNotifier()
    active_notifier = dry_notifier if dry_run else notifier
    ics_bytes = ics_feed.build_invite(first, settings) if first.has_data else b""
    now = datetime.now(settings.tz)
    for n in notifications:
        try:
            if n.channel != "email":
                raise UserError(f"Canale non supportato: {n.channel}")
            msg = messages.render(
                "reminder",
                user=settings.display_name,
                contact=n.contact,
                prediction=first,
                n_days=first.days_until,
                templates_dir=settings.templates_dir,
            )
            atts = (
                [Attachment("ciclo.ics", ics_bytes)]
                if settings.notifications.attach_ics and ics_bytes
                else None
            )
            if not n.contact.email:
                raise UserError(f"Il contatto {n.contact.id} non ha email.")
            if active_notifier is None:
                active_notifier = make_notifier(settings)
            active_notifier.send(n.contact.email, msg.subject, msg.text, msg.html, atts)
            sent += 1
            if not dry_run:
                scheduler.mark_sent(state, n, now)
                store.save_state(state, today)  # persist after every successful send
        except ConfigError:
            raise
        except Exception as exc:
            failed += 1
            errors.append(f"{n.contact.id}: {type(exc).__name__}")

    feed_status = "disattivato"
    if do_publish:
        feed_ics = ics_feed.build_feed(predictions, settings, state, today=today)
        if dry_run:
            feed_status = "dry-run (non pubblicato)"
        else:
            try:
                feed_status = publish.publish(feed_ics, settings, state, now)
            except ConfigError as exc:
                feed_status = f"errore: {exc}"
                errors.append("feed")
            except requests.RequestException as exc:
                feed_status = f"errore: {type(exc).__name__}"
                errors.append("feed")

    state["last_run"] = now.isoformat(timespec="seconds")
    state["last_prediction"] = (
        {
            "anchor": first.anchor.isoformat() if first.anchor else None,
            "start": first.start.isoformat() if first.start else None,
            "end": first.end.isoformat() if first.end else None,
            "confidence": first.confidence,
            "computed_at": now.isoformat(timespec="seconds"),
        }
        if first.has_data
        else None
    )
    if not dry_run:
        store.save_state(state, today)

    result = {
        "dry_run": dry_run,
        "today": today.isoformat(),
        "status": first.status,
        "confidence": first.confidence,
        "due": len(notifications),
        "sent": sent,
        "failed": failed,
        "feed": feed_status,
        "errors": errors,
        "sync": report.to_dict(),
    }
    write_step_summary(
        [
            "### cycle-notifier",
            f"- Modalità: {'prova (dry-run)' if dry_run else 'reale'}",
            f"- Fonti lette: {len(report.sources)}",
            f"- Periodi in archivio: {report.periods_total}",
            f"- Stato previsione: {first.status}",
            f"- Promemoria dovuti: {len(notifications)}, inviati: {sent}, falliti: {failed}",
            f"- Feed: {feed_status.split(':')[0]}",
        ]
    )
    return result


# ---------------------------------------------------------------------------
# Feed / dispatch helpers
# ---------------------------------------------------------------------------
def build_feed_now(settings: Settings, today: date | None = None) -> tuple[bytes, dict[str, Any]]:
    """Build the current feed without saving state (state returned for callers that save)."""
    today = today or today_local(settings)
    store = Store(settings)
    state = store.load_state()
    preds = predictor.predict_many(
        _periods(settings, store), settings.prediction, today, max(3, settings.feed.events_ahead)
    )
    return ics_feed.build_feed(preds, settings, state, today=today), state


def new_feed_token() -> str:
    return secrets.token_urlsafe(24)


def ingest_dispatch(settings: Settings, event_path: str | Path | None = None) -> Path:
    """Write a repository_dispatch ``client_payload`` to data/imports/shortcut-<ts>.json."""
    event_path = event_path or os.environ.get("GITHUB_EVENT_PATH")
    if not event_path or not Path(event_path).exists():
        raise ConfigError("GITHUB_EVENT_PATH non impostato o inesistente.")
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    payload = event.get("client_payload")
    if not isinstance(payload, dict) or not isinstance(payload.get("samples"), list):
        raise UserError("client_payload senza 'samples'.")
    payload.setdefault("source", "ios_shortcut")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    settings.imports_dir.mkdir(parents=True, exist_ok=True)
    out = settings.imports_dir / f"shortcut-{stamp}.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out
