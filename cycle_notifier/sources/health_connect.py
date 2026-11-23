"""Android Health Connect export (zip with a SQLite database). Unofficial table names.

Tables are discovered at runtime: any table whose name contains ``menstruation``.
There is no cloud API; the user exports data manually from Health Connect.
"""

from __future__ import annotations

import re
import sqlite3
import tempfile
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from ..models import FlowDay, Period, SourceResult
from ._tolerant import sanitize
from .base import FileAdapter, SourceContext

_FLOW_INT = {0: "unspecified", 1: "light", 2: "medium", 3: "heavy"}


def _local_day(epoch_ms: int, offset_s: int | None, ctx: SourceContext) -> date | None:
    try:
        moment = datetime.fromtimestamp(epoch_ms / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
    if offset_s is not None:
        return (moment + timedelta(seconds=offset_s)).date()
    return moment.astimezone(ctx.tz).date()


def _pick(cols: list[str], pattern: str, exclude: str = r"offset|zone") -> str | None:
    for c in cols:
        if re.search(pattern, c, re.I) and not re.search(exclude, c, re.I):
            return c
    return None


class HealthConnectAdapter(FileAdapter):
    name = "health_connect"

    def detect(self, path: Path, head: bytes) -> float:
        if head.startswith(b"SQLite format 3"):
            return 0.8
        if path.suffix.lower() == ".zip" and (b".db" in head or b".sqlite" in head):
            return 0.9
        return 0.0

    def parse(self, path: Path, ctx: SourceContext) -> SourceResult:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                db_path = path
                if path.suffix.lower() == ".zip":
                    with zipfile.ZipFile(path) as zf:
                        dbs = [n for n in zf.namelist() if n.endswith((".db", ".sqlite"))]
                        if not dbs:
                            return SourceResult(self.name, error="Nessun database nello zip.")
                        db_path = Path(zf.extract(dbs[0], tmp))
                return self._read_db(db_path, ctx)
        except (OSError, zipfile.BadZipFile, sqlite3.Error) as exc:
            return SourceResult(self.name, error=f"Export Health Connect illeggibile: {exc}")

    def _read_db(self, db_path: Path, ctx: SourceContext) -> SourceResult:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        periods: list[Period] = []
        flows: list[FlowDay] = []
        warnings: list[str] = []
        try:
            tables = [
                r[0]
                for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
                if re.search("menstruation", r[0], re.I)
            ]
            if not tables:
                warnings.append("Nessuna tabella 'menstruation' trovata nel database.")
            for table in tables:
                cols = [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]
                start_c = _pick(cols, r"start|begin")
                end_c = _pick(cols, r"end|stop")
                time_c = _pick(cols, r"time|date|instant")
                flow_c = _pick(cols, r"flow")
                s_off = _pick(cols, r"start.*(offset|zone)|(offset|zone)", exclude=r"^end")
                if start_c and end_c:
                    for row in con.execute(
                        f'SELECT "{start_c}","{end_c}","{s_off or start_c}" FROM "{table}"'
                    ):
                        off = row[2] if s_off and isinstance(row[2], int) else None
                        s = _local_day(int(row[0]), off, ctx)
                        e = _local_day(int(row[1]), off, ctx)
                        if s is not None:
                            periods.append(Period(s, e if e and e >= s else None, frozenset({self.name})))
                elif time_c:
                    sel = f'"{time_c}"' + (f',"{flow_c}"' if flow_c else ",NULL")
                    for row in con.execute(f'SELECT {sel} FROM "{table}"'):
                        d = _local_day(int(row[0]), None, ctx)
                        if d is None:
                            continue
                        raw = row[1]
                        flow = _FLOW_INT.get(raw, "unspecified") if isinstance(raw, int) else "unspecified"
                        flows.append(FlowDay(d, self.name, flow))  # type: ignore[arg-type]
        finally:
            con.close()
        p, f = sanitize(periods, flows, ctx, warnings)
        return SourceResult(self.name, p, f, tuple(warnings))
