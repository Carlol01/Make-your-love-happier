"""Generic import formats: CSV ``start_date,end_date[,note]`` and JSON ``{"periods": [...]}``."""

from __future__ import annotations

import json
from pathlib import Path

from ..models import SourceResult
from ._tolerant import parse_with
from .base import FileAdapter, SourceContext


class GenericAdapter(FileAdapter):
    name = "generic"

    def detect(self, path: Path, head: bytes) -> float:
        text = head.decode("utf-8", "ignore").lstrip("﻿").lstrip().lower()
        if path.suffix.lower() == ".csv" and text.startswith("start_date"):
            return 0.9
        if text.startswith("{") and '"periods"' in text:
            try:
                data = json.loads(path.read_bytes())
            except (OSError, ValueError):
                return 0.6
            return 0.85 if isinstance(data, dict) and "periods" in data else 0.3
        return 0.0

    def parse(self, path: Path, ctx: SourceContext) -> SourceResult:
        return parse_with(self.name, path, ctx)
