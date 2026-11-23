"""Apple Health export (``export.zip`` or ``export.xml``), streamed with iterparse."""

from __future__ import annotations

import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import IO
from xml.etree import ElementTree as ET

from ..models import FlowDay, SourceResult
from .base import FileAdapter, SourceContext

FLOW_TYPE = "HKCategoryTypeIdentifierMenstrualFlow"
SPOTTING_TYPE = "HKCategoryTypeIdentifierIntermenstrualBleeding"
_FLOW_MAP = {"light": "light", "medium": "medium", "heavy": "heavy", "unspecified": "unspecified"}


def _flow(value: str) -> str | None:
    tail = value.replace("HKCategoryValueMenstrualFlow", "").lower()
    if tail in ("none", ""):
        return None
    return _FLOW_MAP.get(tail, "unspecified")


@contextmanager
def _open_export(path: Path) -> Iterator[IO[bytes]]:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.endswith("export.xml") and "cda" not in n.lower()]
            if not names:
                raise ValueError("export.xml non trovato nello zip")
            with zf.open(sorted(names, key=len)[0]) as fh:
                yield fh
    else:
        with path.open("rb") as fh:
            yield fh


class AppleHealthAdapter(FileAdapter):
    name = "apple_health"

    def detect(self, path: Path, head: bytes) -> float:
        if path.suffix.lower() == ".zip" and b"export.xml" in head:
            return 0.95
        if path.suffix.lower() == ".xml" and (b"<HealthData" in head or b"HKCategory" in head):
            return 0.95
        return 0.0

    def parse(self, path: Path, ctx: SourceContext) -> SourceResult:
        flows: list[FlowDay] = []
        try:
            with _open_export(path) as fh:
                for _, elem in ET.iterparse(fh, events=("end",)):
                    if elem.tag != "Record":
                        elem.clear()
                        continue
                    rtype = elem.get("type")
                    if rtype in (FLOW_TYPE, SPOTTING_TYPE):
                        flow = (
                            _flow(elem.get("value", ""))
                            if rtype == FLOW_TYPE
                            else ("spotting" if ctx.include_spotting else None)
                        )
                        raw = elem.get("startDate", "")
                        if flow is not None and raw:
                            try:
                                when = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S %z")
                            except ValueError:
                                when = None
                            if when is not None:
                                day = when.astimezone(ctx.tz).date()
                                if day <= ctx.today:
                                    flows.append(FlowDay(day, self.name, flow))  # type: ignore[arg-type]
                    elem.clear()
        except (OSError, ValueError, zipfile.BadZipFile, ET.ParseError) as exc:
            return SourceResult(self.name, error=f"Export Apple Health illeggibile: {exc}")
        warnings = () if flows else ("Nessun dato MenstrualFlow trovato.",)
        return SourceResult(self.name, (), tuple(flows), warnings)
