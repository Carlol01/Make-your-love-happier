import base64
import email

import pytest

from cycle_notifier.config import ConfigError
from cycle_notifier.notify import Attachment, make_notifier
from cycle_notifier.notify.base import DryRunNotifier
from cycle_notifier.notify.resend import ResendNotifier
from cycle_notifier.notify.smtp import SmtpNotifier

from .conftest import FakeResponse, FakeSession

ENV = {
    "SMTP_HOST": "smtp.example.com",
    "SMTP_PORT": "465",
    "SMTP_USER": "user",
    "SMTP_PASSWORD": "pw",
    "SMTP_FROM": "Promemoria <noreply@example.com>",
}


class FakeSMTP:
    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, **kw):
        self.host, self.port, self.kw = host, port, kw
        self.logged = None
        self.messages = []
        self.tls = False
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, u, p):
        self.logged = (u, p)

    def starttls(self, context=None):
        self.tls = True

    def send_message(self, msg):
        self.messages.append(msg)


@pytest.fixture(autouse=True)
def _reset():
    FakeSMTP.instances.clear()


def test_smtp_ssl_on_465(make_settings, monkeypatch):
    monkeypatch.setattr("smtplib.SMTP_SSL", FakeSMTP)
    n = make_notifier(make_settings(**ENV))
    assert isinstance(n, SmtpNotifier)
    n.send(
        "marco@example.com", "Oggetto", "Testo", "<p>Testo</p>", [Attachment("ciclo.ics", b"BEGIN:VCALENDAR")]
    )
    (smtp,) = FakeSMTP.instances
    assert smtp.port == 465 and smtp.logged == ("user", "pw")
    msg = smtp.messages[0]
    assert msg["To"] == "marco@example.com" and msg["Reply-To"] == "noreply@example.com"
    assert msg["List-Unsubscribe"].startswith("<mailto:")
    names = [p.get_filename() for p in msg.walk() if p.get_filename()]
    assert names == ["ciclo.ics"]
    assert msg.get_body(("html",)) is not None


def test_smtp_starttls_on_587_and_reply_to(make_settings, monkeypatch):
    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    n = make_notifier(make_settings(**{**ENV, "SMTP_PORT": "587", "SMTP_REPLY_TO": "giulia@example.com"}))
    n.send("marco@example.com", "S", "T")
    (smtp,) = FakeSMTP.instances
    assert smtp.tls and smtp.messages[0]["Reply-To"] == "giulia@example.com"


def test_smtp_missing_config(make_settings):
    with pytest.raises(ConfigError):
        make_notifier(make_settings())


def test_resend_payload_and_request(make_settings):
    session = FakeSession({"https://api.resend.com/emails": FakeResponse(json_data={"id": "abc"})})
    n = ResendNotifier("key123", "Promemoria <noreply@example.com>", session)  # type: ignore[arg-type]
    ident = n.send("marco@example.com", "S", "T", "<p>T</p>", [Attachment("ciclo.ics", b"xyz")])
    assert ident == "abc"
    method, url, kw = session.calls[0]
    assert method == "POST" and kw["headers"]["Authorization"] == "Bearer key123"
    body = kw["json"]
    assert body["to"] == ["marco@example.com"] and body["html"] == "<p>T</p>"
    assert base64.b64decode(body["attachments"][0]["content"]) == b"xyz"


def test_resend_http_error_raises(make_settings):
    import requests

    n = ResendNotifier("k", "f@example.com", FakeSession({}))  # type: ignore[arg-type]
    with pytest.raises(requests.HTTPError):
        n.send("a@example.com", "S", "T")


def test_provider_selection(make_settings):
    st = make_settings(EMAIL_PROVIDER="resend", RESEND_API_KEY="k", RESEND_FROM="f@example.com")
    assert isinstance(make_notifier(st), ResendNotifier)
    with pytest.raises(ConfigError):
        make_notifier(make_settings(EMAIL_PROVIDER="carrier-pigeon"))


def test_dry_run_notifier_records_only():
    n = DryRunNotifier()
    assert n.send("a@example.com", "S", "T") == "dry-run"
    assert n.sent == [{"to": "a@example.com", "subject": "S"}]


def test_message_is_valid_rfc822(make_settings):
    n = SmtpNotifier("h", 465, "u", "p", "Promemoria <noreply@example.com>")
    msg = n.build("marco@example.com", "Oggetto è", "Testo", None, None)
    parsed = email.message_from_bytes(msg.as_bytes())
    assert parsed["Subject"] and parsed["Message-ID"]
