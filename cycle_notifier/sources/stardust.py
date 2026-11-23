"""Stardust export. No public format: delegates to the tolerant parser (best-effort)."""

from __future__ import annotations

from pathlib import Path

from ..models import SourceResult
from ._tolerant import parse_with
from .base import FileAdapter, SourceContext


class StardustAdapter(FileAdapter):
    name = "stardust"

    def detect(self, path: Path, head: bytes) -> float:
        return 0.7 if "stardust" in path.name.lower() else 0.0

    def parse(self, path: Path, ctx: SourceContext) -> SourceResult:
        return parse_with(self.name, path, ctx)
