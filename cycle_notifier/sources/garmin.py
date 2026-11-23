"""Garmin Connect source (unofficial, via the optional ``garminconnect`` package).

Prefers the ``GARMIN_TOKENS`` secret (token dump produced locally by
``garmin-login``, which handles MFA) and falls back to ``GARMIN_EMAIL`` /
``GARMIN_PASSWORD``. The API is unofficial and may break without notice.
The client is injectable so tests never need the real library.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from ..models import FlowDay, Period, SourceResult
from ._tolerant import _key_variants, parse_date, sanitize, walk_json
from .base import SourceContext

# Specific keys always denote a period start; generic ones only count next to a length
# (the response wrapper itself carries startDate/endDate for the requested range).
SPECIFIC_START_KEYS = {"period_start_date", "cycle_start_date", "menstruation_start_date", "first_day"}
GENERIC_START_KEYS = {"start_date", "startdate", "start"}
LENGTH_KEYS = {"period_length", "periodlength", "menstruation_length", "bleeding_days"}
END_KEYS = {"end_date", "enddate", "period_end_date", "end"}

ClientFactory = Callable[[SourceContext], Any]


def default_client(ctx: SourceContext) -> Any:  # pragma: no cover - needs the real library/network
    """Create and log in a real garminconnect client."""
    from garminconnect import Garmin

    tokens = ctx.settings.get("GARMIN_TOKENS")
    if tokens:
        client = Garmin()
        client.login(tokenstore=tokens)
        return client
    email, password = ctx.settings.get("GARMIN_EMAIL"), ctx.settings.get("GARMIN_PASSWORD")
    client = Garmin(email, password)
    client.login()
    return client


def _walk(obj: Any, source: str, order: str, ctx: SourceContext) -> list[Period]:
    out: list[Period] = []

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for i in node:
                visit(i)
        elif isinstance(node, dict):
            keys: dict[str, Any] = {}
            for k, v in node.items():
                for variant in _key_variants(k):
                    keys.setdefault(variant, v)
            has_length = any(isinstance(keys.get(k), int) for k in LENGTH_KEYS)
            candidates = SPECIFIC_START_KEYS | (GENERIC_START_KEYS if has_length else set())
            start = next((keys[k] for k in sorted(candidates) if keys.get(k)), None)
            s = parse_date(start, order, ctx.tz) if start else None
            if s is not None:
                end = next((keys[k] for k in END_KEYS if keys.get(k)), None)
                e = parse_date(end, order, ctx.tz) if end else None
                length = next((keys[k] for k in LENGTH_KEYS if isinstance(keys.get(k), int)), None)
                if e is None and length and 0 < length <= 15:
                    e = s + timedelta(days=length - 1)
                out.append(Period(s, e, frozenset({source})))
                return
            for v in node.values():
                visit(v)

    visit(obj)
    return out


class GarminAdapter:
    name = "garmin"
    kind = "remote"

    def __init__(self, client_factory: ClientFactory | None = None) -> None:
        self._factory = client_factory

    def detect(self, path: Path, head: bytes) -> float:
        text = head.decode("utf-8", "ignore")
        if path.suffix.lower() == ".json" and re.search(r"menstrual|periodLength", text):
            return 0.6
        return 0.0

    def parse(self, path: Path, ctx: SourceContext) -> SourceResult:
        import json

        try:
            data = json.loads(path.read_bytes().decode("utf-8-sig"))
        except (OSError, ValueError) as exc:
            return SourceResult(self.name, error=f"JSON non valido: {exc}")
        return self._to_result(data, ctx)

    def _to_result(self, data: Any, ctx: SourceContext) -> SourceResult:
        warnings: list[str] = []
        periods = _walk(data, self.name, ctx.date_order, ctx)
        p, f = sanitize(periods, [], ctx, warnings)
        return SourceResult(self.name, p, f, tuple(warnings))

    def _configured(self, ctx: SourceContext) -> bool:
        s = ctx.settings
        return bool(s.get("GARMIN_TOKENS") or (s.get("GARMIN_EMAIL") and s.get("GARMIN_PASSWORD")))

    def fetch(self, ctx: SourceContext) -> SourceResult:
        if self._factory is None and not self._configured(ctx):
            return SourceResult(self.name, warnings=("Garmin non configurato: saltato.",), skipped=True)
        try:
            client = (self._factory or default_client)(ctx)
            start = ctx.since or ctx.today - timedelta(days=365)
            end = ctx.today
            if hasattr(client, "get_menstrual_calendar_data"):
                data = client.get_menstrual_calendar_data(start.isoformat(), end.isoformat())
                result = self._to_result(data, ctx)
                if result.periods:
                    return result
            flows: list[FlowDay] = []
            if hasattr(client, "get_menstrual_data_for_date"):
                day = max(start, ctx.today - timedelta(days=120))
                while day <= end:
                    resp = client.get_menstrual_data_for_date(day.isoformat())
                    if resp:
                        _, fl = walk_json({"date": day.isoformat(), **resp}, self.name, ctx)
                        flows.extend(fl)
                    day += timedelta(days=1)
            warnings: list[str] = []
            p, f = sanitize([], flows, ctx, warnings)
            return SourceResult(self.name, p, f, tuple(warnings))
        except Exception as exc:  # adapters never raise
            return SourceResult(self.name, error=f"Garmin non disponibile: {type(exc).__name__}: {exc}")
