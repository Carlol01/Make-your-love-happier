"""Prediction of the next period from historical starts."""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from datetime import date, timedelta

from .config import PredictionSettings
from .models import Confidence, Period, Prediction, Status


def cycle_lengths(periods: Sequence[Period], cfg: PredictionSettings) -> list[int]:
    """Valid consecutive start-to-start lengths (within min/max cycle days)."""
    starts = sorted({p.start for p in periods})
    lengths = [(b - a).days for a, b in zip(starts, starts[1:], strict=False)]
    return [n for n in lengths if cfg.min_cycle_days <= n <= cfg.max_cycle_days]


def _mean(values: Sequence[int], weighted: bool) -> float:
    if not weighted:
        return statistics.fmean(values)
    weights = range(1, len(values) + 1)  # oldest -> newest
    return sum(v * w for v, w in zip(values, weights, strict=True)) / sum(weights)


def _durations(periods: Sequence[Period], cfg: PredictionSettings) -> list[int]:
    out = []
    for p in sorted(periods, key=lambda p: p.start):
        if p.end is None or p.end_estimated:
            continue
        n = (p.end - p.start).days + 1
        if cfg.min_period_days <= n <= cfg.max_period_days:
            out.append(n)
    return out[-6:]


def _confidence(n: int, sd: float | None) -> Confidence:
    if n >= 6 and sd is not None and sd <= 2:
        return "high"
    if n >= 3 and sd is not None and sd <= 4:
        return "medium"
    if n >= 1:
        return "low"
    return "default"


def predict(periods: Sequence[Period], cfg: PredictionSettings, today: date) -> Prediction:
    """Compute the next-period prediction relative to ``today``."""
    if not periods:
        return Prediction(
            anchor=None,
            start=None,
            end=None,
            avg_cycle=float(cfg.default_cycle_days),
            avg_duration=cfg.default_period_days,
            sd_cycle=None,
            n_cycles=0,
            confidence="default",
            status="no_data",
            days_until=None,
        )
    ordered = sorted(periods, key=lambda p: p.start)
    last = ordered[-1]
    recent = cycle_lengths(ordered, cfg)[-cfg.history_cycles :]
    avg_cycle = _mean(recent, cfg.weighted) if recent else float(cfg.default_cycle_days)
    sd = statistics.pstdev(recent) if len(recent) >= 2 else None
    durations = _durations(ordered, cfg)
    avg_dur = round(statistics.fmean(durations)) if durations else cfg.default_period_days

    anchor = last.start
    next_start = anchor + timedelta(days=round(avg_cycle))
    next_end = next_start + timedelta(days=avg_dur - 1)
    in_period = anchor <= today <= anchor + timedelta(days=avg_dur - 1) or (
        last.end is not None and anchor <= today <= last.end
    )
    status: Status
    if in_period:
        status = "in_period"
    elif (today - anchor).days > cfg.stale_after_factor * avg_cycle:
        status = "stale"
    elif next_start < today:
        status = "late"
    else:
        status = "upcoming"
    margin = math.ceil(sd if sd else 3)
    return Prediction(
        anchor=anchor,
        start=next_start,
        end=next_end,
        avg_cycle=avg_cycle,
        avg_duration=avg_dur,
        sd_cycle=sd,
        n_cycles=len(recent),
        confidence=_confidence(len(recent), sd),
        status=status,
        days_until=(next_start - today).days,
        window=(next_start - timedelta(days=margin), next_start + timedelta(days=margin)),
    )


def predict_many(
    periods: Sequence[Period], cfg: PredictionSettings, today: date, count: int = 3
) -> list[Prediction]:
    """Return up to ``count`` successive predictions.

    Further predictions are chained only while the first is still meaningful
    (``upcoming`` or ``in_period``); late/stale cycles yield a single entry.
    """
    first = predict(periods, cfg, today)
    out = [first]
    if first.status not in ("upcoming", "in_period"):
        return out
    step = round(first.avg_cycle)
    margin = math.ceil(first.sd_cycle if first.sd_cycle else 3)
    assert first.start is not None
    prev_start = first.start
    for _ in range(1, count):
        start = prev_start + timedelta(days=step)
        out.append(
            Prediction(
                anchor=prev_start,
                start=start,
                end=start + timedelta(days=first.avg_duration - 1),
                avg_cycle=first.avg_cycle,
                avg_duration=first.avg_duration,
                sd_cycle=first.sd_cycle,
                n_cycles=first.n_cycles,
                confidence=first.confidence,
                status="upcoming",
                days_until=(start - today).days,
                window=(start - timedelta(days=margin), start + timedelta(days=margin)),
            )
        )
        prev_start = start
    return out[:count]
