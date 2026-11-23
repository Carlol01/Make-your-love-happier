"""Flo GDPR data export (JSON). Best-effort: structure is not documented."""

from __future__ import annotations

from pathlib import Path

from ..models import SourceResult
from ._tolerant import parse_with
from .base import FileAdapter, SourceContext


class FloAdapter(FileAdapter):
    name = "flo"

    def detect(self, path: Path, head: bytes) -> float:
        text = head.decode("utf-8", "ignore")
        if "period_start_date" in text or "operationalData" in text:
            return 0.9
        return 0.5 if "flo" in path.name.lower() and path.suffix.lower() == ".json" else 0.0

    def parse(self, path: Path, ctx: SourceContext) -> SourceResult:
        return parse_with(self.name, path, ctx)
