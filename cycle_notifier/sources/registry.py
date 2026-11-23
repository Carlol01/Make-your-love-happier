"""Adapter registry and format autodetection."""

from __future__ import annotations

import zipfile
from pathlib import Path

from ._tolerant import TolerantAdapter
from .apple_health import AppleHealthAdapter
from .base import SourceAdapter
from .clue import ClueAdapter
from .flo import FloAdapter
from .garmin import GarminAdapter
from .generic import GenericAdapter
from .health_connect import HealthConnectAdapter
from .ics import IcsAdapter
from .ios_shortcut import IosShortcutAdapter
from .natural_cycles import NaturalCyclesAdapter
from .period_tracker_gp import PeriodTrackerAdapter
from .stardust import StardustAdapter

HEAD_BYTES = 64 * 1024
THRESHOLD = 0.5

FILE_ADAPTERS: list[SourceAdapter] = [
    IcsAdapter(),
    AppleHealthAdapter(),
    IosShortcutAdapter(),
    HealthConnectAdapter(),
    ClueAdapter(),
    FloAdapter(),
    NaturalCyclesAdapter(),
    StardustAdapter(),
    PeriodTrackerAdapter(),
    GenericAdapter(),
    GarminAdapter(),
]
TOLERANT = TolerantAdapter()


def get_adapter(name: str) -> SourceAdapter:
    """Look an adapter up by name (including ``tolerant`` and ``garmin``)."""
    for adapter in (*FILE_ADAPTERS, TOLERANT):
        if adapter.name == name:
            return adapter
    raise KeyError(f"Sorgente sconosciuta: {name}")


def read_head(path: Path) -> bytes:
    """First 64 KB of a file; for zips, the member names joined (without extraction)."""
    if path.suffix.lower() == ".zip" or zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as zf:
                return "\n".join(zf.namelist()).encode()
        except zipfile.BadZipFile:
            pass
    with path.open("rb") as fh:
        return fh.read(HEAD_BYTES)


def autodetect(path: Path) -> SourceAdapter:
    """Choose the adapter with the highest score; below 0.5 use the tolerant parser."""
    head = read_head(path)
    best: SourceAdapter = TOLERANT
    best_score = 0.0
    for adapter in FILE_ADAPTERS:
        score = adapter.detect(path, head)
        if score > best_score:
            best, best_score = adapter, score
    return best if best_score >= THRESHOLD else TOLERANT
