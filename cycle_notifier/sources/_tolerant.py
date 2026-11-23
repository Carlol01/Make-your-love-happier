"""Best-effort parsing of unknown JSON/CSV exports.

The walker looks for period start/end keys or per-day flow indicators and maps
them to :class:`Period` / :class:`FlowDay`. Dates in the future or before 2000
are dropped.
"""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dateutil import parser as dateparser

from ..models import FlowDay, Period, SourceResult
from .base import FileAdapter, SourceContext

START_KEYS = {
    "start", "start_date", "startdate", "period_start", "period_start_date", "periodstart",
    "begin", "inizio", "data_inizio", "from",
}  # fmt: skip
END_KEYS = {
    "end", "end_date", "enddate", "period_end", "period_end_date", "periodend",
    "fine", "data_fine", "to",
}  # fmt: skip
DAY_KEYS = {"date", "day", "data", "giorno", "datetime", "timestamp", "time"}
INDICATOR_RE = re.compile(r"period|menstru|flow|bleed|ciclo|periodo|mestruaz", re.I)
FALSY = {"", "0", "no", "false", "none", "n", "-", "nessuno", "null", "off", "0.0"}
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def norm_key(key: str) -> str:
    """Lowercase, strip accents, collapse non-alphanumerics to underscores."""
    text = unicodedata.normalize("NFKD", str(key)).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    # camelCase -> snake_case is already lowercased; keep joined variants too.
    return text


def _key_variants(key: str) -> set[str]:
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", str(key))
    return {norm_key(key), norm_key(snake)}


def parse_date(value: Any, date_order: str = "DMY", tz: ZoneInfo | None = None) -> date | None:
    """Parse ISO strings, epoch seconds/milliseconds and free-form dates."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return _local(value, tz)
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) or (
        isinstance(value, str) and re.fullmatch(r"\d{9,13}", value.strip())
    ):
        num = float(value)
        if num > 1e11:
            num /= 1000.0
        try:
            return _local(datetime.fromtimestamp(num, tz=ZoneInfo("UTC")), tz)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if _ISO_RE.match(text):
        try:
            return _local(datetime.fromisoformat(text.replace("Z", "+00:00")), tz)
        except ValueError:
            try:
                return date.fromisoformat(text[:10])
            except ValueError:
                return None
    try:
        parsed = dateparser.parse(
            text, dayfirst=date_order.upper().startswith("D"), yearfirst=date_order.upper() == "YMD"
        )
    except (ValueError, OverflowError, dateparser.ParserError):
        return None
    return _local(parsed, tz)


def _local(value: datetime, tz: ZoneInfo | None) -> date:
    if value.tzinfo is not None and tz is not None:
        return value.astimezone(tz).date()
    return value.date()


def _flow_from(value: Any) -> str | None:
    text = str(value).lower()
    for word in ("spotting", "light", "medium", "heavy"):
        if word in text:
            return word
    if text.strip() in FALSY:
        return None
    return "unspecified"


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, (dict, list)):
        return bool(value)
    return str(value).strip().lower() not in FALSY


def sanitize(
    periods: Iterable[Period],
    flow_days: Iterable[FlowDay],
    ctx: SourceContext,
    warnings: list[str],
) -> tuple[tuple[Period, ...], tuple[FlowDay, ...]]:
    """Drop future dates, dates before 2000 and inverted periods."""
    floor = date(2000, 1, 1)
    out_p: list[Period] = []
    dropped = 0
    for p in periods:
        if p.start < floor or p.start > ctx.today:
            dropped += 1
            continue
        end = p.end
        if end is not None and (end < p.start or end < floor):
            end = None
        if end is not None and end > ctx.today:
            end = None  # still ongoing
        out_p.append(Period(p.start, end, p.sources, p.manual, p.end_estimated, p.note))
    out_f = []
    for f in flow_days:
        if f.day < floor or f.day > ctx.today:
            dropped += 1
            continue
        out_f.append(f)
    if dropped:
        warnings.append(f"{dropped} date scartate (future o precedenti al 2000).")
    return tuple(out_p), tuple(out_f)


# ---------------------------------------------------------------------------
# JSON walker
# ---------------------------------------------------------------------------
def walk_json(obj: Any, source: str, ctx: SourceContext) -> tuple[list[Period], list[FlowDay]]:
    """Recursively collect periods and flow days from arbitrary JSON."""
    periods: list[Period] = []
    flows: list[FlowDay] = []
    order, tz = ctx.date_order, ctx.tz

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, dict):
            return
        keys = {}
        for k, v in node.items():
            for variant in _key_variants(k):
                keys.setdefault(variant, v)
        start = next((keys[k] for k in START_KEYS if k in keys and keys[k] not in (None, "")), None)
        start_d = parse_date(start, order, tz) if start is not None else None
        if start_d is not None:
            end = next((keys[k] for k in END_KEYS if k in keys and keys[k] not in (None, "")), None)
            end_d = parse_date(end, order, tz) if end is not None else None
            periods.append(Period(start_d, end_d, frozenset({source})))
            return
        day = next((keys[k] for k in DAY_KEYS if k in keys), None)
        day_d = parse_date(day, order, tz) if day is not None else None
        if day_d is not None:
            flow = None
            hit = False
            for k, v in node.items():
                if norm_key(k) in DAY_KEYS:
                    continue
                if str(k).lower() == "type" and isinstance(v, str):
                    if INDICATOR_RE.search(v) or "spotting" in v.lower():
                        hit = True
                        flow = (
                            "spotting"
                            if "spotting" in v.lower()
                            else (_flow_from(node.get("value")) or "unspecified")
                        )
                    continue
                if INDICATOR_RE.search(str(k)) and _truthy(v):
                    hit = True
                    flow = _flow_from(v) or "unspecified"
            if hit:
                flows.append(FlowDay(day_d, source, flow))  # type: ignore[arg-type]
                return
        for v in node.values():
            visit(v)

    visit(obj)
    return periods, flows


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
def _sniff(text: str) -> csv.Dialect | type[csv.excel]:
    sample = text[:4096]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        first = sample.splitlines()[0] if sample else ""
        delim = max(",;\t|", key=first.count)
        d = csv.excel()
        d.delimiter = delim
        return d


def read_csv_rows(text: str) -> list[dict[str, str]]:
    """Read CSV with sniffed dialect and normalised headers."""
    text = text.lstrip("﻿")
    if not text.strip():
        return []
    reader = csv.reader(io.StringIO(text), _sniff(text))
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        return []
    headers = [norm_key(h) for h in rows[0]]
    return [dict(zip(headers, r, strict=False)) for r in rows[1:]]


def parse_csv_rows(
    rows: list[dict[str, str]], source: str, ctx: SourceContext
) -> tuple[list[Period], list[FlowDay], list[str]]:
    periods: list[Period] = []
    flows: list[FlowDay] = []
    warnings: list[str] = []
    if not rows:
        return periods, flows, warnings
    cols = set(rows[0])
    start_col = next((c for c in rows[0] if c in START_KEYS), None)
    end_col = next((c for c in rows[0] if c in END_KEYS), None)
    note_col = "note" if "note" in cols else ("notes" if "notes" in cols else None)
    if start_col:
        for row in rows:
            s = parse_date(row.get(start_col), ctx.date_order, ctx.tz)
            if s is None:
                continue
            e = parse_date(row.get(end_col), ctx.date_order, ctx.tz) if end_col else None
            note = (row.get(note_col) or "").strip() or None if note_col else None
            periods.append(Period(s, e, frozenset({source}), note=note))
        return periods, flows, warnings
    day_col = next((c for c in rows[0] if c in DAY_KEYS), None)
    ind_cols = [c for c in rows[0] if INDICATOR_RE.search(c)]
    if not day_col:
        warnings.append("Nessuna colonna data riconosciuta.")
        return periods, flows, warnings
    if not ind_cols:
        warnings.append("Nessuna colonna con indicatore di mestruazione riconosciuta.")
        return periods, flows, warnings
    for row in rows:
        d = parse_date(row.get(day_col), ctx.date_order, ctx.tz)
        if d is None:
            continue
        for c in ind_cols:
            val = row.get(c, "")
            if _truthy(val):
                flows.append(FlowDay(d, source, _flow_from(val)))  # type: ignore[arg-type]
                break
    return periods, flows, warnings


def parse_text(text: str, source: str, ctx: SourceContext) -> SourceResult:
    """Parse JSON or CSV text tolerantly and return a sanitised SourceResult."""
    warnings: list[str] = []
    stripped = text.lstrip("﻿").lstrip()
    periods: list[Period]
    flows: list[FlowDay]
    if stripped[:1] in "[{":
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError as exc:
            return SourceResult(source, error=f"JSON non valido: {exc}")
        periods, flows = walk_json(obj, source, ctx)
    else:
        rows = read_csv_rows(stripped)
        periods, flows, warnings = parse_csv_rows(rows, source, ctx)
    if not periods and not flows:
        warnings.append("Nessun dato di ciclo riconosciuto.")
    p, f = sanitize(periods, flows, ctx, warnings)
    return SourceResult(source, p, f, tuple(warnings))


def read_text(path: Path) -> str:
    """Read a text file trying UTF-8 then Latin-1."""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeError:
            continue
    return raw.decode("utf-8", "replace")


class TolerantAdapter(FileAdapter):
    """Fallback adapter for any JSON/CSV file."""

    name = "tolerant"

    def detect(self, path: Path, head: bytes) -> float:
        return 0.1 if path.suffix.lower() in {".json", ".csv", ".txt", ".tsv"} else 0.05

    def parse(self, path: Path, ctx: SourceContext) -> SourceResult:
        try:
            return parse_text(read_text(path), self.name, ctx)
        except Exception as exc:  # adapters never raise
            return SourceResult(self.name, error=f"Errore di lettura: {exc}")


def parse_with(source: str, path: Path, ctx: SourceContext) -> SourceResult:
    """Parse ``path`` tolerantly but label results with ``source``."""
    try:
        return parse_text(read_text(path), source, ctx)
    except Exception as exc:
        return SourceResult(source, error=f"Errore di lettura: {exc}")
