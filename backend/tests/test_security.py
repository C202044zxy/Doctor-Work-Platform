"""B acceptance on latest A/T13/T14 contracts; no production mock routes."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from fastapi import Depends
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_auth_grants import client as auth_client
from test_auth_grants import headers, login, put_code

from app import audit, auth
from app.models import AuditLog, Patient, User
from app.security import require_permission

client = auth_client


@pytest.mark.parametrize(
    "uid,expected",
    [
        (3, [200, 403, 403, 403, 403]),
        (2, [200, 200, 403, 403, 403]),
        (1, [200, 403, 200, 200, 200]),
    ],
)
def test_fifteen_permission_combinations(client, uid, expected):
    for resource, permission, status in zip(
        ["patients", "review", "audit", "users", "templates"],
        ["patient.read", "emr.review", "audit.read", "user.manage", "template.manage"],
        expected,
        strict=True,
    ):
        path = f"/api/contract/{resource}"
        client.app.add_api_route(
            path, lambda: auth.ok({}), dependencies=[Depends(require_permission(permission))]
        )
        response = client.get(path, headers=headers(client, uid))
        assert response.status_code == status
        if status == 403:
            assert "Missing permission" in response.json()["message"]


def create_patient(client):
    response = client.post(
        "/api/patients",
        headers=headers(client),
        json={"name": "Audit Example", "gender": "male", "department": "General Medicine"},
    )
    assert response.status_code == 200
    return response.json()["data"]["patient_no"]


def test_scope_changes_use_live_database(client):
    number = create_patient(client)
    old_headers = headers(client, 3)
    assert client.get(f"/api/patients/{number}", headers=old_headers).status_code == 404
    with client.app.state.sessions() as db:
        db.get(User, 3).department_id = 1
        db.commit()
    assert client.get(f"/api/patients/{number}", headers=old_headers).status_code == 200
    assert client.get("/api/patients", headers=old_headers).json()["data"]["total"] == 1
    with client.app.state.sessions() as db:
        db.get(User, 3).role_id = db.get(User, 1).role_id
        db.commit()
    client.app.add_api_route(
        "/api/contract/audit",
        lambda: auth.ok({}),
        dependencies=[Depends(require_permission("audit.read"))],
    )
    assert client.get("/api/contract/audit", headers=old_headers).status_code == 200


def test_send_and_consume_concurrency(client, monkeypatch):
    sent = []
    monkeypatch.setattr(auth, "deliver_code", lambda settings, address, code: sent.append(code))
    client.app.state.settings.smtp_host = "smtp.example.test"
    ticket = login(client)

    def send(_):
        return client.post("/api/auth/send-code", json={"ticket": ticket}).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(send, range(8))).count(200) == 1
    assert len(sent) == 1
    assert 295 <= client.app.state.cache.ttl(auth.code_key(1)) <= 300
    assert sent[0].encode() not in client.app.state.cache.get(auth.code_key(1))

    def consume(_):
        return client.post(
            "/api/auth/verify-code", json={"ticket": ticket, "code": sent[0]}
        ).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(consume, range(8))).count(200) == 1
    with client.app.state.sessions() as db:
        assert all(
            sent[0] not in str(row.__dict__) and ticket not in str(row.__dict__)
            for row in db.scalars(select(AuditLog))
        )


def test_expired_code_and_daily_limit(client, monkeypatch):
    ticket = login(client)
    put_code(client, ticket)
    client.app.state.cache.delete(auth.code_key(1))
    assert (
        client.post("/api/auth/verify-code", json={"ticket": ticket, "code": "123456"}).status_code
        == 401
    )
    client.app.state.settings.smtp_host = "smtp.example.test"
    client.app.state.cache.set(f"auth:send:daily:1:{datetime.now(UTC).date()}", 20, ex=86400)
    response = client.post("/api/auth/send-code", json={"ticket": ticket})
    assert response.status_code == 429 and "Daily" in response.text


def test_audit_metadata_and_failure_isolation(client, monkeypatch, caplog):
    number = create_patient(client)
    assert client.get(f"/api/patients/{number}", headers=headers(client)).status_code == 200
    with client.app.state.sessions() as db:
        logs = list(db.scalars(select(AuditLog).order_by(AuditLog.id)))
        assert [(row.action, row.object_id, row.result) for row in logs] == [
            ("patient.create", number, "success"),
            ("patient.view", number, "success"),
        ]
        assert all(row.user_id == 1 and row.ip and row.method for row in logs)
        # T12 lists the actor by name. It is snapshotted at write time rather
        # than joined on read, so a later rename cannot rewrite the past.
        assert all(row.username == "admin" for row in logs)

    def broken(**values):
        raise RuntimeError("private database connection details")

    monkeypatch.setattr(audit, "AuditLog", broken)
    surviving_number = create_patient(client)
    assert "Audit persistence failed" in caplog.text and "private database" not in caplog.text
    with client.app.state.sessions() as db:
        assert db.scalar(select(Patient).where(Patient.patient_no == surviving_number)) is not None


def test_audit_is_append_only_in_database(client):
    create_patient(client)
    for statement in ["UPDATE audit_logs SET action='tampered'", "DELETE FROM audit_logs"]:
        with (
            pytest.raises(DBAPIError, match="append-only"),
            client.app.state.engine.begin() as connection,
        ):
            connection.execute(text(statement))


def test_default_protection_and_uniform_errors(client):
    def failure():
        raise RuntimeError("private information")

    client.app.add_api_route("/api/failure", failure, methods=["POST"])
    assert client.post("/api/failure").status_code == 401
    assert client.get("/missing").json() == {"code": 404, "message": "Not Found", "data": None}
    client._transport.raise_server_exceptions = False
    response = client.post("/api/failure", headers=headers(client))
    assert response.status_code == 500 and response.json()["data"] is None
    assert "private" not in response.text
    with client.app.state.sessions() as db:
        assert list(db.scalars(select(AuditLog.status_code).order_by(AuditLog.id))) == [401, 500]


def test_smtp_timeout_tls_and_redaction(client, monkeypatch):
    import smtplib

    settings = client.app.state.settings
    settings.smtp_host = "smtp.example.test"
    settings.smtp_port = 465

    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 10
        raise TimeoutError("secret SMTP data")

    monkeypatch.setattr(smtplib, "SMTP_SSL", timeout)
    ticket = login(client)
    response = client.post("/api/auth/send-code", json={"ticket": ticket})
    assert response.status_code == 502 and "secret SMTP" not in response.text
    assert not client.app.state.cache.exists(auth.code_key(1))
    settings.smtp_port, settings.smtp_starttls = 25, False
    with pytest.raises(Exception, match="SMTP requires TLS"):
        auth.deliver_code(settings, "admin@example.test", "123456")


def test_unconfigured_jwt_secret_fails_closed(client):
    old_headers = headers(client)
    client.app.state.settings.jwt_secret = ""
    assert client.get("/api/me", headers=old_headers).status_code == 503
