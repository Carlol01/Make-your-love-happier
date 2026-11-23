from datetime import date

from cycle_notifier.i18n import fmt_date, norm_lang, plural_days


def test_fmt_date_italian():
    assert fmt_date(date(2026, 11, 26), "it") == "giovedì 26 novembre"


def test_fmt_date_english():
    assert fmt_date(date(2026, 11, 26), "en") == "Thursday, November 26"


def test_plural_days():
    assert plural_days(1) == "1 giorno"
    assert plural_days(3) == "3 giorni"
    assert plural_days(1, "en") == "1 day"
    assert plural_days(2, "en") == "2 days"


def test_norm_lang_falls_back_to_italian():
    assert norm_lang("EN-us") == "en"
    assert norm_lang("de") == "it"
    assert norm_lang(None) == "it"
