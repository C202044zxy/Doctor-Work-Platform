# ruff: noqa: F811
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.auth import code_key, store_verification_code, ticket_key
from app.models import AuditLog, NotifyOutbox, User
from app.otp import reserve_send
from app.sms import MockSmsProvider
from tests.test_auth_grants import client, headers, login  # noqa: F401


def send(client, ticket):
    return client.post("/api/auth/sms/send", json={"ticket": ticket, "phone": "13800138000"})


def preview(client, ticket):
    return client.post("/api/auth/sms/preview", json={"ticket": ticket})


def test_sms_login_preview_one_time_and_audit_redaction(client):
    client.app.state.settings.app_env = "dev"
    ticket = login(client)
    result = send(client, ticket)
    assert result.status_code == 200
    assert result.json()["data"]["mock"] is True
    assert "code" not in result.json()["data"]
    message = preview(client, ticket)
    assert message.headers["cache-control"] == "no-store"
    code = message.json()["data"]["code"]
    assert len(code) == 6 and code.isdigit()
    assert client.app.state.cache.get(code_key(1)) != code.encode()
    with client.app.state.sessions() as db:
        row = db.scalar(select(NotifyOutbox))
        assert row.code == code and row.status == "sent(mock)"
        assert "13800138000" not in row.target
        for event in db.scalars(select(AuditLog)):
            assert code not in json.dumps(event.detail)
            assert ticket not in event.path
    other_ticket = login(client)
    assert preview(client, other_ticket).status_code == 404
    body = {"ticket": ticket, "code": code}
    verified = client.post("/api/auth/sms/verify", json=body)
    assert verified.status_code == 200
    data = verified.json()["data"]
    assert data["mock"] is True
    auth = {"Authorization": "Bearer " + data["access_token"]}
    assert client.get("/api/me", headers=auth).status_code == 200
    assert client.post("/api/auth/sms/verify", json=body).status_code == 401
    assert preview(client, ticket).status_code == 401


def test_sms_validation_configuration_and_admin_outbox(client):
    ticket = login(client)
    assert send(client, ticket).status_code == 404
    assert preview(client, ticket).status_code == 404
    client.app.state.settings.app_env = "dev"
    assert send(client, "invalid-ticket").status_code == 401
    for phone in ["123", "1380013800x", "23800138000"]:
        assert (
            client.post("/api/auth/sms/send", json={"ticket": ticket, "phone": phone}).status_code
            == 422
        )
    assert send(client, ticket).status_code == 200
    assert client.get("/api/notify-outbox").status_code == 401
    assert client.get("/api/notify-outbox", headers=headers(client, 2)).status_code == 403
    result = client.get("/api/notify-outbox", headers=headers(client)).json()["data"]
    assert result["total"] == 1 and result["items"][0]["code"]
    client.app.state.settings.app_env = "production"
    assert (
        client.get("/api/notify-outbox", headers=headers(client)).json()["data"]["items"][0]["code"]
        is None
    )
    assert (
        client.post("/api/auth/sms/verify", json={"ticket": ticket, "code": "123456"}).status_code
        == 404
    )
    MockSmsProvider().send(client.app.state.sessions, "13800138000", "123456", expose_code=False)
    with client.app.state.sessions() as db:
        assert db.scalar(select(NotifyOutbox).order_by(NotifyOutbox.id.desc())).code is None


def test_sms_and_email_share_cooldown_and_daily_limit(client, monkeypatch):
    client.app.state.settings.app_env = "dev"
    client.app.state.settings.smtp_host = "smtp.example.test"
    monkeypatch.setattr("app.auth.deliver_code", lambda *args: None)
    ticket = login(client)
    assert client.post("/api/auth/send-code", json={"ticket": ticket}).status_code == 200
    rejected = send(client, ticket)
    assert rejected.status_code == 429
    assert 1 <= int(rejected.headers["retry-after"]) <= 60
    cache = client.app.state.cache
    cache.delete("auth:send:cooldown:1")
    assert send(client, ticket).status_code == 200
    assert client.post("/api/auth/send-code", json={"ticket": ticket}).status_code == 429
    # New password tickets cannot bypass per-account reservations either.
    assert send(client, login(client)).status_code == 429
    cache.delete("auth:send:cooldown:1")
    with pytest.raises(HTTPException) as exc:
        reserve_send(cache, 1, daily_limit=2)
    assert exc.value.status_code == 429


def test_sms_expiry_replacement_and_attempt_lock(client):
    client.app.state.settings.app_env = "dev"
    ticket = login(client)
    assert send(client, ticket).status_code == 200
    code = preview(client, ticket).json()["data"]["code"]
    assert 0 < client.app.state.cache.ttl(code_key(1)) <= 300
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert (
            client.post("/api/auth/sms/verify", json={"ticket": ticket, "code": wrong}).status_code
            == 401
        )
    assert not client.app.state.cache.exists(ticket_key(ticket))
    assert preview(client, ticket).status_code == 401
    ticket = login(client)
    client.app.state.cache.delete("auth:send:cooldown:1")
    assert send(client, ticket).status_code == 200
    store_verification_code(
        client.app.state.cache, client.app.state.settings.jwt_secret, ticket, "876543"
    )
    assert preview(client, ticket).status_code == 404
    client.app.state.cache.expire(code_key(1), 0)
    assert (
        client.post("/api/auth/sms/verify", json={"ticket": ticket, "code": "876543"}).status_code
        == 401
    )
    client.app.state.cache.expire(ticket_key(ticket), 0)
    assert send(client, ticket).status_code == 401


def test_sms_provider_failure_and_disabled_user(client):
    client.app.state.settings.app_env = "dev"
    ticket = login(client)

    class BrokenProvider:
        def send(self, *args, **kwargs):
            raise OSError("private provider details")

    client.app.state.sms_provider = BrokenProvider()
    result = send(client, ticket)
    assert result.status_code == 503
    assert "private" not in result.text
    assert not client.app.state.cache.exists(code_key(1))
    assert preview(client, ticket).status_code == 404
    with client.app.state.sessions() as db:
        db.get(User, 1).status = "disabled"
        db.commit()
    assert send(client, ticket).status_code == 401


def test_sms_redis_outage_is_explicit(client):
    client.app.state.settings.app_env = "dev"
    ticket = login(client)
    client.app.state.cache = None
    assert send(client, ticket).status_code == 503
