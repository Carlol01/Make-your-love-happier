"""Tiny built-in localisation: weekday/month names and plurals (IT/EN)."""

from __future__ import annotations

from datetime import date

WEEKDAYS = {
    "it": ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
}
MONTHS = {
    "it": [
        "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
        "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
    ],
    "en": [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ],
}  # fmt: skip
SUPPORTED = tuple(WEEKDAYS)


def norm_lang(lang: str | None) -> str:
    """Normalise a language code to a supported one (default ``it``)."""
    code = (lang or "it").lower()[:2]
    return code if code in SUPPORTED else "it"


def fmt_date(d: date, lang: str = "it") -> str:
    """Format like ``giovedì 25 novembre`` / ``Thursday, November 25``."""
    lang = norm_lang(lang)
    wd = WEEKDAYS[lang][d.weekday()]
    month = MONTHS[lang][d.month - 1]
    if lang == "en":
        return f"{wd}, {month} {d.day}"
    return f"{wd} {d.day} {month}"


def plural_days(n: int, lang: str = "it") -> str:
    """``1 giorno`` / ``N giorni`` (``1 day`` / ``N days``)."""
    lang = norm_lang(lang)
    if lang == "en":
        return f"{n} day" if abs(n) == 1 else f"{n} days"
    return f"{n} giorno" if abs(n) == 1 else f"{n} giorni"
