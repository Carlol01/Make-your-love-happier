"""Message rendering (subject, text, simple HTML) with overridable templates."""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path
from string import Template

from .i18n import fmt_date, norm_lang, plural_days
from .models import Contact, Prediction

_FOOTER_IT = """—
Ricevi questo promemoria perché hai accettato di riceverlo da $user.
È una stima automatica e può variare di qualche giorno.
Per non riceverlo più, rispondi a questa email o scrivilo a $user."""

_FOOTER_EN = """—
You receive this reminder because you agreed to receive it from $user.
It is an automatic estimate and may vary by a few days.
To stop receiving it, reply to this email or tell $user."""

BUILTIN: dict[str, dict[str, str]] = {
    "it": {
        "reminder_subject": "Promemoria: il ciclo di $user è previsto tra $n_days",
        "reminder_body": (
            "Ciao $contact,\n"
            "tra $n_days ($start_date) è previsto l'inizio del ciclo di $user: "
            "di solito dura circa $duration_days (fino a $end_date circa).\n"
            "$confidence_line\n\n"
            "Un piccolo gesto di attenzione fa sempre piacere 💛\n\n" + _FOOTER_IT
        ),
        "invite_subject": "$user ti propone un promemoria (solo se vuoi)",
        "invite_body": (
            "Ciao $contact,\n"
            "$user vorrebbe inviarti, se sei d'accordo, un breve promemoria qualche giorno "
            "prima dell'inizio del suo ciclo, così puoi essere più attento/a.\n\n"
            'Se vuoi riceverlo, rispondi a questa email con "sì". '
            "Se preferisci di no, non devi fare nulla: non riceverai niente.\n\n"
            "$feed_line"
            "Maggiori informazioni: $guide_url\n\n"
            "Puoi cambiare idea in qualsiasi momento.\n"
        ),
        "test_subject": "[TEST] Promemoria: il ciclo di $user è previsto tra $n_days",
        "confidence_high": "La previsione è piuttosto affidabile.",
        "confidence_medium": "La data può variare di circa ±$sd giorni.",
        "confidence_low": "Ci sono pochi dati: la data è indicativa.",
        "test_banner": "[Questo è un messaggio di prova: nessuna data reale è stata usata.]\n\n",
    },
    "en": {
        "reminder_subject": "Reminder: $user's period is expected in $n_days",
        "reminder_body": (
            "Hi $contact,\n"
            "in $n_days ($start_date) $user's period is expected to start; "
            "it usually lasts about $duration_days (until about $end_date).\n"
            "$confidence_line\n\n"
            "A small thoughtful gesture is always appreciated 💛\n\n" + _FOOTER_EN
        ),
        "invite_subject": "$user would like to send you a reminder (only if you want)",
        "invite_body": (
            "Hi $contact,\n"
            "$user would like to send you, if you agree, a short reminder a few days "
            "before her period starts, so you can be more mindful.\n\n"
            'If you want it, reply to this email with "yes". '
            "If not, do nothing: you will receive nothing.\n\n"
            "$feed_line"
            "More information: $guide_url\n\n"
            "You can change your mind at any time.\n"
        ),
        "test_subject": "[TEST] Reminder: $user's period is expected in $n_days",
        "confidence_high": "The estimate is fairly reliable.",
        "confidence_medium": "The date may vary by about ±$sd days.",
        "confidence_low": "There is little data: the date is only indicative.",
        "test_banner": "[This is a test message: no real date was used.]\n\n",
    },
}


@dataclass(frozen=True)
class Message:
    subject: str
    text: str
    html: str


def load_template(name: str, lang: str, templates_dir: Path | None) -> str:
    """Return the override ``{templates_dir}/{lang}/{name}.txt`` or the built-in text."""
    lang = norm_lang(lang)
    if templates_dir is not None:
        override = templates_dir / lang / f"{name}.txt"
        if override.is_file():
            return override.read_text(encoding="utf-8")
    return BUILTIN[lang][name]


def _confidence_line(pred: Prediction, lang: str, templates_dir: Path | None) -> str:
    key = {"high": "high", "medium": "medium"}.get(pred.confidence, "low")
    sd = max(1, round(pred.sd_cycle)) if pred.sd_cycle else 3
    return Template(load_template(f"confidence_{key}", lang, templates_dir)).safe_substitute(sd=sd)


def to_html(text: str) -> str:
    """Convert plain text to minimal inline-styled HTML."""
    paras = [
        '<p style="margin:0 0 12px">' + html.escape(p).replace("\n", "<br>") + "</p>"
        for p in text.split("\n\n")
    ]
    return (
        '<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;'
        'font-size:15px;line-height:1.5;color:#222">' + "".join(paras) + "</div>"
    )


def render(
    name: str,
    *,
    user: str,
    contact: Contact,
    prediction: Prediction | None,
    n_days: int | None = None,
    lang: str | None = None,
    templates_dir: Path | None = None,
    extra: dict[str, str] | None = None,
) -> Message:
    """Render a message. ``name`` is ``reminder``, ``test`` or ``invite``."""
    lang = norm_lang(lang or contact.lang)
    values: dict[str, str] = {"user": user, "contact": contact.name}
    if prediction is not None and prediction.start is not None and prediction.end is not None:
        days = prediction.days_until if n_days is None else n_days
        values.update(
            n_days=plural_days(days or 0, lang),
            start_date=fmt_date(prediction.start, lang),
            end_date=fmt_date(prediction.end, lang),
            duration_days=plural_days(prediction.avg_duration, lang),
            confidence_line=_confidence_line(prediction, lang, templates_dir),
        )
    values.update(extra or {})
    body_name = "reminder_body" if name in ("reminder", "test") else f"{name}_body"
    subj_name = f"{name}_subject"
    subject = Template(load_template(subj_name, lang, templates_dir)).safe_substitute(values)
    text = Template(load_template(body_name, lang, templates_dir)).safe_substitute(values)
    if name == "test":
        text = load_template("test_banner", lang, templates_dir) + text
    return Message(subject=subject, text=text, html=to_html(text))
