"""Clue ``.cluedata`` export (JSON): new list format and old ``{"data": [...]}`` format."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import FlowDay, SourceResult
from ._tolerant import _flow_from, parse_date, parse_with, sanitize
from .base import FileAdapter, SourceContext


class ClueAdapter(FileAdapter):
    name = "clue"

    def detect(self, path: Path, head: bytes) -> float:
        if path.suffix.lower() == ".cluedata":
            return 0.95
        text = head.decode("utf-8", "ignore")
        if '"type"' in text and '"period"' in text and text.lstrip().startswith("["):
            return 0.7
        if '"data"' in text and '"period"' in text and '"day"' in text:
            return 0.7
        return 0.0

    def parse(self, path: Path, ctx: SourceContext) -> SourceResult:
        try:
            obj = json.loads(path.read_bytes().decode("utf-8-sig"))
        except (OSError, ValueError) as exc:
            return SourceResult(self.name, error=f"JSON non valido: {exc}")
        flows: list[FlowDay] = []
        if isinstance(obj, list):
            items: list[Any] = obj
            for it in items:
                if isinstance(it, dict) and it.get("type") in ("period", "spotting"):
                    d = parse_date(it.get("date"), ctx.date_order, ctx.tz)
                    if d is None:
                        continue
                    if it["type"] == "spotting":
                        flows.append(FlowDay(d, self.name, "spotting"))
                        continue
                    opt = (
                        (it.get("value") or {}).get("option")
                        if isinstance(it.get("value"), dict)
                        else it.get("value")
                    )
                    flows.append(FlowDay(d, self.name, _flow_from(opt)))  # type: ignore[arg-type]
        elif isinstance(obj, dict) and isinstance(obj.get("data"), list):
            for it in obj["data"]:
                if not isinstance(it, dict):
                    continue
                d = parse_date(it.get("day") or it.get("date"), ctx.date_order, ctx.tz)
                val = it.get("period")
                if d is None or val in (None, False, 0, "", "none"):
                    continue
                flows.append(FlowDay(d, self.name, _flow_from(val)))  # type: ignore[arg-type]
        if not flows:
            return parse_with(self.name, path, ctx)  # unknown layout: tolerant fallback
        warnings: list[str] = []
        _, f = sanitize([], flows, ctx, warnings)
        return SourceResult(self.name, (), f, tuple(warnings))
