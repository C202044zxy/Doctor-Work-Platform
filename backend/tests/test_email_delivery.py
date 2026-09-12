import re
import smtplib

from test_auth_grants import client as auth_client
from test_auth_grants import login

client = auth_client


def test_email_delivery(client, monkeypatch):
    client.app.state.settings.smtp_host = None
    ticket = login(client)
    assert client.post("/api/auth/send-code", json={"ticket": ticket}).status_code == 503
    client.app.state.settings.smtp_host = "smtp.example.test"
    sent = []

    class SMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self, **kwargs):
            pass

        def send_message(self, message):
            sent.append(message)

    monkeypatch.setattr(smtplib, "SMTP", SMTP)
    r = client.post("/api/auth/send-code", json={"ticket": ticket})
    assert r.status_code == 200
    code = re.search(r"\b\d{6}\b", sent[0].get_content())[0]
    assert code not in r.text
    assert sent[0]["To"] == "admin@example.test"
    assert client.post("/api/auth/send-code", json={"ticket": ticket}).status_code == 429
    assert (
        client.post("/api/auth/verify-code", json={"ticket": ticket, "code": code}).status_code
        == 200
    )
    assert client.post("/api/auth/send-code", json={"ticket": ticket}).status_code == 401
    ticket = login(client)
    client.app.state.cache.delete("auth:send:cooldown:1")

    def fail(*args):
        raise OSError("connection failed")

    monkeypatch.setattr(SMTP, "send_message", fail)
    assert client.post("/api/auth/send-code", json={"ticket": ticket}).status_code == 502


def test_email_daily_limit(client):
    from datetime import UTC, datetime

    ticket = login(client)
    client.app.state.settings.smtp_host = "smtp.example.test"
    client.app.state.cache.set(f"auth:send:daily:1:{datetime.now(UTC).date()}", 20, ex=86400)
    response = client.post("/api/auth/send-code", json={"ticket": ticket})
    assert response.status_code == 429
    assert "Daily" in response.json()["message"]
