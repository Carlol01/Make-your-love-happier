"""Merge periods and flow days from several sources into a clean history."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

from .config import PredictionSettings
from .models import FlowDay, Period


def _span(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def merge(
    periods: Iterable[Period],
    flow_days: Iterable[FlowDay],
    cfg: PredictionSettings,
    today: date,
    excluded_days: Iterable[date] = (),
    stored: Iterable[Period] = (),
    gap_tolerance: int = 1,
) -> tuple[list[Period], list[str]]:
    """Merge everything into a sorted list of periods plus warnings.

    1. expand periods to days (missing end -> start + default - 1, flagged as
       estimated, unless it is the ongoing current period);
    2. add flow days (spotting filtered unless enabled);
    3. subtract excluded days;
    4. cluster days with ``gap_tolerance`` missing days allowed, uniting sources;
    5. manual periods win over overlapping clusters;
    6. drop clusters longer than ``max_period_days * 1.5`` with a warning;
    7. the union with ``stored`` history means nothing is ever deleted except
       through ``excluded_days``.
    """
    warnings: list[str] = []
    excluded = set(excluded_days)
    items = sorted([*stored, *periods], key=lambda p: (p.start, p.manual))
    manual = [p for p in items if p.manual]
    auto = [p for p in items if not p.manual]

    flow_set: dict[date, set[str]] = {}
    for fd in flow_days:
        if fd.flow == "spotting" and not cfg.include_spotting:
            continue
        flow_set.setdefault(fd.day, set()).add(fd.source)

    day_sources: dict[date, set[str]] = {d: set(s) for d, s in flow_set.items()}
    real_days: set[date] = set(flow_set)
    tails: list[tuple[Period, list[date]]] = []
    ongoing_start: date | None = None
    last_start = auto[-1].start if auto else None

    for p in auto:
        if p.end is not None and not p.end_estimated:
            for d in _span(p.start, p.end):
                day_sources.setdefault(d, set()).update(p.sources)
                real_days.add(d)
            continue
        # Estimated or missing end.
        if p.end is not None:
            span = _span(p.start, p.end)
        else:
            length = cfg.default_period_days
            if p.start == last_start and (today - p.start).days < length:
                ongoing_start = p.start
                span = _span(p.start, max(p.start, today))
            else:
                span = _span(p.start, p.start + timedelta(days=length - 1))
        day_sources.setdefault(p.start, set()).update(p.sources)
        real_days.add(p.start)  # the start date itself is a real observation
        tails.append((p, span[1:]))

    # An estimated tail is kept only when no real data shows the actual length.
    for p, tail in tails:
        horizon = p.start + timedelta(days=cfg.max_period_days)
        if any(p.start < d <= horizon for d in real_days):
            continue
        for d in tail:
            day_sources.setdefault(d, set()).update(p.sources)

    for d in excluded:
        day_sources.pop(d, None)

    clusters: list[list[date]] = []
    for d in sorted(day_sources):
        if clusters and (d - clusters[-1][-1]).days - 1 <= gap_tolerance:
            clusters[-1].append(d)
        else:
            clusters.append([d])

    manual_ranges = [(p.start, p.end or p.start) for p in manual]
    result: list[Period] = []
    limit = cfg.max_period_days * 1.5
    for cl in clusters:
        if any(cl[0] <= me and ms <= cl[-1] for ms, me in manual_ranges):
            continue  # manual wins
        length = (cl[-1] - cl[0]).days + 1
        if length > limit:
            warnings.append(f"Periodo di {length} giorni dal {cl[0]} scartato (troppo lungo).")
            continue
        srcs: set[str] = set()
        for d in cl:
            srcs |= day_sources[d]
        ongoing = (
            ongoing_start is not None
            and cl[0] <= ongoing_start <= cl[-1]
            and cl[-1] >= today - timedelta(days=1)
        )
        est_end = cl[-1] not in real_days and not ongoing
        result.append(
            Period(
                start=cl[0],
                end=None if ongoing else cl[-1],
                sources=frozenset(srcs),
                end_estimated=est_end,
            )
        )
    result.extend(manual)
    result.sort(key=lambda p: p.start)
    return result, warnings
