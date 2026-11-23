"""Natural Cycles CSV export (date + Menstruation column). Best-effort."""

from __future__ import annotations

from pathlib import Path

from ..models import SourceResult
from ._tolerant import norm_key, parse_with
from .base import FileAdapter, SourceContext


class NaturalCyclesAdapter(FileAdapter):
    name = "natural_cycles"

    def detect(self, path: Path, head: bytes) -> float:
        if path.suffix.lower() != ".csv":
            return 0.0
        first = head.decode("utf-8", "ignore").lstrip("﻿").splitlines()[:1]
        header = norm_key(first[0]) if first else ""
        if "menstruation" in header and "date" in header:
            return 0.9
        if "natural" in path.name.lower():
            return 0.6
        return 0.0

    def parse(self, path: Path, ctx: SourceContext) -> SourceResult:
        return parse_with(self.name, path, ctx)
