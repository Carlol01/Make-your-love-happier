from dataclasses import replace
from datetime import date

from cycle_notifier.messages import render
from cycle_notifier.models import Contact, Prediction

PRED = Prediction(
    anchor=date(2026, 10, 24),
    start=date(2026, 11, 21),
    end=date(2026, 11, 25),
    avg_cycle=28,
    avg_duration=5,
    sd_cycle=0.0,
    n_cycles=6,
    confidence="high",
    status="upcoming",
    days_until=3,
)
MARCO = Contact(id="marco", name="Marco", email="marco@example.com", consent_given=True)


def test_italian_reminder():
    m = render("reminder", user="Giulia", contact=MARCO, prediction=PRED)
    assert m.subject == "Promemoria: il ciclo di Giulia è previsto tra 3 giorni"
    assert "Ciao Marco," in m.text
    assert "tra 3 giorni (sabato 21 novembre)" in m.text
    assert "fino a mercoledì 25 novembre circa" in m.text
    assert "circa 5 giorni" in m.text
    assert "piuttosto affidabile" in m.text
    assert "Per non riceverlo più, rispondi a questa email" in m.text
    assert "<p" in m.html


def test_singular_day():
    m = render("reminder", user="Giulia", contact=MARCO, prediction=replace(PRED, days_until=1))
    assert "tra 1 giorno" in m.subject


def test_english_reminder():
    m = render("reminder", user="Giulia", contact=replace(MARCO, lang="en"), prediction=PRED)
    assert m.subject == "Reminder: Giulia's period is expected in 3 days"
    assert "Hi Marco," in m.text and "To stop receiving it" in m.text


def test_confidence_lines():
    med = render(
        "reminder", user="G", contact=MARCO, prediction=replace(PRED, confidence="medium", sd_cycle=2.4)
    )
    assert "±2 giorni" in med.text
    low = render("reminder", user="G", contact=MARCO, prediction=replace(PRED, confidence="low"))
    assert "pochi dati" in low.text


def test_test_message_is_labelled():
    m = render("test", user="Giulia", contact=MARCO, prediction=PRED)
    assert m.subject.startswith("[TEST]") and "messaggio di prova" in m.text


def test_invite_asks_for_reply_and_has_guide():
    m = render(
        "invite",
        user="Giulia",
        contact=MARCO,
        prediction=None,
        extra={"feed_line": "", "guide_url": "https://example.com/contatti.html"},
    )
    assert "sì" in m.text and "https://example.com/contatti.html" in m.text


def test_template_override_and_safe_substitution(tmp_path):
    d = tmp_path / "it"
    d.mkdir()
    (d / "reminder_subject.txt").write_text("Ehi $contact, $n_days! $unknown", encoding="utf-8")
    m = render("reminder", user="Giulia", contact=MARCO, prediction=PRED, templates_dir=tmp_path)
    assert m.subject == "Ehi Marco, 3 giorni! $unknown"  # unknown placeholders survive


def test_html_escapes_names():
    evil = replace(MARCO, name="<b>x</b>")
    m = render("reminder", user="Giulia", contact=evil, prediction=PRED)
    assert "<b>x</b>" not in m.html and "&lt;b&gt;" in m.html
