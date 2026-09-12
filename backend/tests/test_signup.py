import json
import re
import smtplib

import pytest
from sqlalchemy import select
from test_auth_grants import client as auth_client

from app.activate_user import activate
from app.auth import issue_token, verify_password
from app.models import User
from app.signup import signup_key

client = auth_client
DETAILS = {
    "username": "new_doctor",
    "name": "New Doctor",
    "email": "New@Example.test",
    "password": "strong-password",
    "department": "General Medicine",
}


@pytest.fixture
def mail(client, monkeypatch):
    sent = []
    client.app.state.settings.smtp_host = "smtp.example.test"

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
    return sent


def start(client, mail):
    response = client.post("/api/auth/signup", json=DETAILS)
    assert response.status_code == 200, response.text
    ticket = response.json()["data"]["ticket"]
    code = re.search(r"\b\d{6}\b", mail[-1].get_content())[0]
    assert code not in response.text
    return {"ticket": ticket, "code": code}


def test_signup_activation_and_login(client, mail):
    body = start(client, mail)
    cache = client.app.state.cache
    raw = cache.get(signup_key(body["ticket"]))
    assert DETAILS["password"] not in raw.decode()
    assert json.loads(raw)["digest"] != body["code"]
    assert 0 < cache.ttl(signup_key(body["ticket"])) <= 300
    assert mail[0]["To"] == "new@example.test"
    with client.app.state.sessions() as db:
        assert db.scalar(select(User).where(User.username == DETAILS["username"])) is None
    assert client.post("/api/auth/signup/verify", json=body).status_code == 200
    assert client.post("/api/auth/signup/verify", json=body).status_code == 401
    credentials = {k: DETAILS[k] for k in ("username", "password")}
    assert client.post("/api/auth/login", json=credentials).status_code == 401
    with client.app.state.sessions() as db:
        user = db.scalar(select(User).where(User.username == DETAILS["username"]))
        assert user.status == "pending" and user.role.name == "junior"
        assert verify_password(DETAILS["password"], user.password_hash)
        token = issue_token(user, client.app.state.settings.jwt_secret)
        assert (
            client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
        )
        with pytest.raises(ValueError):
            activate(db, user.username, "Missing")
        activate(db, user.username, "Cardiology")
        assert user.department.name == "Cardiology"
    assert client.post("/api/auth/login", json=credentials).status_code == 200


@pytest.mark.parametrize(
    "change",
    [
        {"email": "bad"},
        {"password": "short"},
        {"password": "界" * 25},
        {"username": " "},
        {"name": " "},
        {"title": "admin"},
        {"department": "Missing"},
    ],
)
def test_signup_validation(client, mail, change):
    assert client.post("/api/auth/signup", json=DETAILS | change).status_code == 422
    assert not mail


def test_signup_throttle_and_expiry(client, mail):
    body = start(client, mail)
    assert client.post("/api/auth/signup", json=DETAILS).status_code == 429
    client.app.state.cache.delete(signup_key(body["ticket"]))
    assert client.post("/api/auth/signup/verify", json=body).status_code == 401


def test_signup_wrong_codes(client, mail):
    body = start(client, mail)
    wrong = "000000" if body["code"] != "000000" else "111111"
    for _ in range(5):
        assert (
            client.post("/api/auth/signup/verify", json=body | {"code": wrong}).status_code == 401
        )
    assert client.post("/api/auth/signup/verify", json=body).status_code == 429
    assert client.app.state.cache.get(signup_key(body["ticket"])) is None


def test_signup_duplicate_and_delivery_failure(client, mail, monkeypatch):
    assert (
        client.post("/api/auth/signup", json=DETAILS | {"email": "ADMIN@example.test"}).status_code
        == 409
    )

    def fail(*args):
        raise OSError("SMTP unavailable")

    monkeypatch.setattr(smtplib.SMTP, "send_message", fail)
    assert client.post("/api/auth/signup", json=DETAILS).status_code == 502
    assert not list(client.app.state.cache.scan_iter("signup:ticket:*"))
    client.app.state.settings.smtp_host = None
    assert client.post("/api/auth/signup", json=DETAILS).status_code == 503
    client.app.state.cache = None
    assert client.post("/api/auth/signup", json=DETAILS).status_code == 503


def test_signup_duplicate_at_verification(client, mail):
    body = start(client, mail)
    with client.app.state.sessions() as db:
        existing = db.get(User, 1)
        existing.email = "new@example.test"
        db.commit()
    assert client.post("/api/auth/signup/verify", json=body).status_code == 409


def test_signup_tickets_cannot_sign_in(client, mail):
    body = start(client, mail)
    assert client.post("/api/auth/verify-code", json=body).status_code == 401
    assert client.post("/api/auth/send-code", json={"ticket": body["ticket"]}).status_code == 401
    assert client.post("/api/auth/signup/verify", json=body | {"code": "123"}).status_code == 422


@pytest.mark.parametrize("kind", ["email", "ip"])
def test_signup_delivery_limits(client, mail, kind):
    import hashlib

    cache = client.app.state.cache
    if kind == "email":
        key = "signup:email:" + hashlib.sha256(b"new@example.test").hexdigest() + ":daily"
    else:
        key = "signup:ip:" + hashlib.sha256(b"testclient").hexdigest()
    cache.set(key, 20, ex=86400)
    assert client.post("/api/auth/signup", json=DETAILS).status_code == 429
    assert not mail
