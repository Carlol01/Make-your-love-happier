"""Source adapter protocol and shared context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

import requests

from ..config import Settings
from ..models import SourceResult


@dataclass
class SourceContext:
    """Everything an adapter needs: settings, injected ``today``, tz and HTTP session."""

    settings: Settings
    today: date
    tz: ZoneInfo
    http: requests.Session
    since: date | None = None

    @classmethod
    def create(cls, settings: Settings, today: date, http: requests.Session | None = None) -> SourceContext:
        return cls(settings=settings, today=today, tz=settings.tz, http=http or requests.Session())

    @property
    def date_order(self) -> str:
        return self.settings.sources.date_order

    @property
    def include_spotting(self) -> bool:
        return self.settings.prediction.include_spotting


class SourceAdapter(Protocol):
    """A data source. Implementations never raise: errors go in ``SourceResult.error``."""

    name: str
    kind: Literal["remote", "file"]

    def detect(self, path: Path, head: bytes) -> float:
        """Return a confidence 0..1 that ``path`` is in this adapter's format."""
        ...

    def parse(self, path: Path, ctx: SourceContext) -> SourceResult: ...

    def fetch(self, ctx: SourceContext) -> SourceResult: ...


class FileAdapter:
    """Base class for file-only adapters (``fetch`` is a no-op)."""

    name = "base"
    kind: Literal["remote", "file"] = "file"

    def detect(self, path: Path, head: bytes) -> float:  # pragma: no cover - overridden
        return 0.0

    def parse(self, path: Path, ctx: SourceContext) -> SourceResult:  # pragma: no cover
        raise NotImplementedError

    def fetch(self, ctx: SourceContext) -> SourceResult:
        return SourceResult(self.name, error="Questa sorgente funziona solo con file.")
