"""iOS Shortcut payloads: ``{"source":"ios_shortcut","samples":[{"start","end","flow"}]}``."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from ..models import FlowDay, Period, SourceResult
from ._tolerant import parse_date, sanitize
from .base import FileAdapter, SourceContext


class IosShortcutAdapter(FileAdapter):
    name = "ios_shortcut"

    def detect(self, path: Path, head: bytes) -> float:
        if path.name.startswith("shortcut-") and path.suffix == ".json":
            return 0.95
        text = head.decode("utf-8", "ignore")
        return 0.9 if '"ios_shortcut"' in text else 0.0

    def parse(self, path: Path, ctx: SourceContext) -> SourceResult:
        try:
            obj = json.loads(path.read_bytes().decode("utf-8-sig"))
        except (OSError, ValueError) as exc:
            return SourceResult(self.name, error=f"JSON non valido: {exc}")
        samples = obj.get("samples") if isinstance(obj, dict) else None
        if not isinstance(samples, list):
            return SourceResult(self.name, error="Payload senza 'samples'.")
        flows: list[FlowDay] = []
        periods: list[Period] = []
        for s in samples:
            if not isinstance(s, dict):
                continue
            start = parse_date(s.get("start"), "YMD", ctx.tz)
            end = parse_date(s.get("end"), "YMD", ctx.tz) or start
            if start is None or end is None or end < start:
                continue
            flow = str(s.get("flow", "unspecified")).lower()
            if flow not in ("light", "medium", "heavy", "spotting"):
                flow = "unspecified"
            n = (end - start).days + 1
            for i in range(min(n, 15)):
                flows.append(FlowDay(start + timedelta(days=i), self.name, flow))  # type: ignore[arg-type]
        warnings: list[str] = []
        p, f = sanitize(periods, flows, ctx, warnings)
        return SourceResult(self.name, p, f, tuple(warnings))
