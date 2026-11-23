"""Command line interface: ``python -m cycle_notifier <command>``.

Exit codes: 0 ok, 1 partial failure (some email/feed step failed), 2 configuration
or usage error, 3 all sources failed and no stored data.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from . import service
from .config import ConfigError, Settings, load_settings
from .models import Prediction
from .publish import feed_path
from .service import NoDataError, UserError
from .storage import StorageError, Store, atomic_write, generate_key


def _day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"data non valida: {value} (usa AAAA-MM-GG)") from exc


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cycle-notifier", description="Promemoria e feed per il ciclo.")
    p.add_argument("--home", type=Path, help="cartella del progetto (default: auto)")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="pipeline giornaliera")
    r.add_argument("--dry-run", action="store_true", help="non invia e non scrive nulla")
    r.add_argument("--today", type=_day)
    r.add_argument("--no-publish", action="store_true")

    s = sub.add_parser("sync", help="leggi le sorgenti e aggiorna cycles.json")
    s.add_argument("--source", action="append", dest="sources")
    s.add_argument("--file", action="append", dest="files", type=Path)
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--today", type=_day)

    pr = sub.add_parser("predict", help="mostra le prossime previsioni")
    pr.add_argument("--count", type=int, default=3)
    pr.add_argument("--today", type=_day)
    pr.add_argument("--json", action="store_true")

    pv = sub.add_parser("preview", help="anteprima del messaggio (non invia)")
    pv.add_argument("--contact")
    pv.add_argument("--offset", type=int, default=3)
    pv.add_argument("--lang")
    pv.add_argument("--today", type=_day)

    ic = sub.add_parser("ics", help="genera il feed ICS")
    ic.add_argument("--out", type=Path)
    ic.add_argument("--publish", action="store_true")
    ic.add_argument("--new-token", action="store_true", help="genera un nuovo FEED_TOKEN")
    ic.add_argument("--today", type=_day)

    ap = sub.add_parser("add-period", help="aggiungi un periodo manualmente")
    ap.add_argument("start")
    ap.add_argument("end", nargs="?")
    ap.add_argument("--note")

    ex = sub.add_parser("exclude", help="escludi giorni dallo storico")
    ex.add_argument("days", nargs="+")

    sub.add_parser("ingest-dispatch", help="salva il payload di repository_dispatch")

    iv = sub.add_parser("invite", help="invia l'invito (richiesta di consenso)")
    iv.add_argument("id")
    iv.add_argument("--dry-run", action="store_true")

    te = sub.add_parser("test-email", help="invia un'email [TEST] a un contatto")
    te.add_argument("id")
    te.add_argument("--dry-run", action="store_true")

    sub.add_parser("garmin-login", help="login Garmin locale (gestisce MFA), stampa GARMIN_TOKENS")

    en = sub.add_parser("encrypt", help="cifra data/*.json con CYCLES_KEY")
    en.add_argument("--generate-key", action="store_true")
    sub.add_parser("decrypt", help="decifra data/*.json.enc")
    return p


def _print_prediction(pred: Prediction, lang: str = "it") -> None:
    from .i18n import fmt_date

    if pred.start is None:
        print("Nessun dato: impossibile prevedere.")
        return
    window = ""
    if pred.window:
        window = f" (finestra {pred.window[0]:%d/%m} - {pred.window[1]:%d/%m})"
    print(
        f"{fmt_date(pred.start, lang)} -> {fmt_date(pred.end, lang)}"  # type: ignore[arg-type]
        f"  [{pred.status}, tra {pred.days_until} g, affidabilità {pred.confidence}]{window}"
    )


def _cmd_run(st: Settings, a: argparse.Namespace) -> int:
    res = service.run(st, a.today, dry_run=a.dry_run, do_publish=not a.no_publish)
    mode = "DRY-RUN" if res["dry_run"] else "RUN"
    print(f"[{mode}] stato={res['status']} confidenza={res['confidence']}")
    print(
        f"  fonti={len(res['sync']['sources'])} periodi={res['sync']['periods_total']} "
        f"promemoria dovuti={res['due']} inviati={res['sent']} falliti={res['failed']}"
    )
    print(f"  feed: {res['feed']}")
    for w in res["sync"]["warnings"]:
        print(f"  avviso: {w}")
    return 1 if res["errors"] else 0


def _cmd_sync(st: Settings, a: argparse.Namespace) -> int:
    rep = service.sync(st, a.today, sources=a.sources, files=a.files, dry_run=a.dry_run)
    for name, info in rep.sources.items():
        flag = f"ERRORE: {info['error']}" if info["error"] else "ok"
        print(f"{name}: {info['periods']} elementi, {flag}")
    for w in rep.warnings:
        print(f"avviso: {w}")
    print(f"Periodi in archivio: {rep.periods_total}{' (dry-run, nulla salvato)' if a.dry_run else ''}")
    return 0


def _cmd_predict(st: Settings, a: argparse.Namespace) -> int:
    preds = service.predict(st, a.today, a.count)
    if a.json:
        print(json.dumps([service.prediction_to_dict(p) for p in preds], indent=2))
    else:
        for p in preds:
            _print_prediction(p, st.default_lang)
    return 0


def _cmd_preview(st: Settings, a: argparse.Namespace) -> int:
    out = service.preview(st, a.contact, a.offset, a.lang, a.today)
    print(f"Oggetto: {out['subject']}\n")
    print(out["body"])
    return 0


def _cmd_ics(st: Settings, a: argparse.Namespace) -> int:
    if a.new_token:
        token = service.new_feed_token()
        print(f"Nuovo FEED_TOKEN: {token}")
        print("Aggiornalo con: gh secret set FEED_TOKEN  (poi rigenera il sito) e riabbonati al calendario.")
        return 0
    ics, state = service.build_feed_now(st, a.today)
    if a.publish:
        from datetime import datetime

        from .publish import publish

        store = Store(st)
        print(publish(ics, st, state, datetime.now(st.tz)))
        store.save_state(state)
    out = a.out or (feed_path(st, "none") if not a.publish else None)
    if out:
        atomic_write(out, ics)
        print(f"Scritto {out}")
    return 0


def _cmd_garmin_login(st: Settings, a: argparse.Namespace) -> int:
    try:
        from garminconnect import Garmin
    except ImportError:
        print("Installa l'extra: pip install '.[garmin]'", file=sys.stderr)
        return 2
    email = input("Email Garmin: ").strip()
    password = getpass.getpass("Password Garmin: ")
    client = Garmin(email, password, prompt_mfa=lambda: input("Codice MFA: ").strip())
    client.login()
    dumper = getattr(getattr(client, "garth", None), "dumps", None) or getattr(
        getattr(client, "client", None), "dumps", None
    )
    if dumper is None:
        print("Questa versione di garminconnect non espone dumps().", file=sys.stderr)
        return 2
    token = dumper()
    if not isinstance(token, str):
        token = base64.b64encode(json.dumps(token).encode()).decode()
    print("\nSalva il seguente valore come secret GARMIN_TOKENS (non condividerlo):\n")
    print(token)
    return 0


def _cmd_encrypt(st: Settings, a: argparse.Namespace, encrypt: bool = True) -> int:
    if encrypt and a.generate_key:
        print(f"CYCLES_KEY={generate_key()}")
        return 0
    changed = Store(st).migrate(encrypt=encrypt)
    print("Convertiti: " + (", ".join(changed) if changed else "nessun file"))
    return 0


def dispatch(a: argparse.Namespace, st: Settings) -> int:
    c = a.command
    if c == "run":
        return _cmd_run(st, a)
    if c == "sync":
        return _cmd_sync(st, a)
    if c == "predict":
        return _cmd_predict(st, a)
    if c == "preview":
        return _cmd_preview(st, a)
    if c == "ics":
        return _cmd_ics(st, a)
    if c == "add-period":
        print(json.dumps(service.add_period(st, a.start, a.end, a.note)))
        return 0
    if c == "exclude":
        print(json.dumps(service.exclude_days(st, a.days)))
        return 0
    if c == "ingest-dispatch":
        print(f"Scritto {service.ingest_dispatch(st)}")
        return 0
    if c == "invite":
        print(json.dumps(service.invite(st, a.id, dry_run=a.dry_run)))
        return 0
    if c == "test-email":
        print(json.dumps(service.send_test(st, a.id, dry_run=a.dry_run)))
        return 0
    if c == "garmin-login":
        return _cmd_garmin_login(st, a)
    if c == "encrypt":
        return _cmd_encrypt(st, a, True)
    if c == "decrypt":
        return _cmd_encrypt(st, a, False)
    return 2  # pragma: no cover


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.home)
        return dispatch(args, settings)
    except NoDataError as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 3
    except (ConfigError, UserError, StorageError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
