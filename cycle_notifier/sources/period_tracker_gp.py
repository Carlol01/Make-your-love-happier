"""Period Tracker (GP Apps) CSV export. Best-effort via the tolerant parser."""

from __future__ import annotations

from pathlib import Path

from ..models import SourceResult
from ._tolerant import parse_with
from .base import FileAdapter, SourceContext


class PeriodTrackerAdapter(FileAdapter):
    name = "period_tracker_gp"

    def detect(self, path: Path, head: bytes) -> float:
        name = path.name.lower()
        if "period" in name and "tracker" in name:
            return 0.7
        lines = head.decode("utf-8", "ignore").lower().splitlines()
        if path.suffix.lower() == ".csv" and lines and "period start" in lines[0]:
            return 0.6
        return 0.0

    def parse(self, path: Path, ctx: SourceContext) -> SourceResult:
        return parse_with(self.name, path, ctx)
