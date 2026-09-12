"""Real ES256 WebAuthn verification using a software authenticator."""

import hashlib
import json
import re
import smtplib

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from test_auth_grants import client as auth_client
from test_auth_grants import headers, login
from webauthn.helpers import bytes_to_base64url as b64

from app.models import User

client = auth_client


def options(client, kind, uid=1):
    r = client.post(f"/api/auth/passkeys/{kind}/options", headers=headers(client, uid))
    assert r.status_code == 200, r.text
    return r.json()["data"]


def credential(
    opts, key, kind, origin="http://localhost:5173", flags=5, count=1, rp="localhost", handle=1
):
    cid = b"test-credential"
    cd = json.dumps(
        {
            "type": "webauthn.create" if kind == "register" else "webauthn.get",
            "challenge": opts["public_key"]["challenge"],
            "origin": origin,
        }
    ).encode()
    data = (
        hashlib.sha256(rp.encode()).digest()
        + bytes([flags | (64 if kind == "register" else 0)])
        + count.to_bytes(4, "big")
    )
    response = {"clientDataJSON": b64(cd)}
    if kind == "register":
        n = key.public_key().public_numbers()
        cose = cbor2.dumps(
            {1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")}
        )
        data += bytes(16) + len(cid).to_bytes(2, "big") + cid + cose
        response["attestationObject"] = b64(
            cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": data})
        )
    else:
        response.update(
            {
                "authenticatorData": b64(data),
                "signature": b64(
                    key.sign(data + hashlib.sha256(cd).digest(), ec.ECDSA(hashes.SHA256()))
                ),
                "userHandle": b64(hashlib.sha256(f"dwp-user:{handle}".encode()).digest()),
            }
        )
    return {
        "ticket": opts["ticket"],
        "credential": {
            "id": b64(cid),
            "rawId": b64(cid),
            "type": "public-key",
            "response": response,
        },
    }


def register(client):
    key = ec.generate_private_key(ec.SECP256R1())
    opts = options(client, "register")
    assert opts["public_key"]["authenticatorSelection"]["userVerification"] == "required"
    r = client.post(
        "/api/auth/passkeys/register/verify",
        headers=headers(client),
        json=credential(opts, key, "register"),
    )
    assert r.status_code == 200, r.text
    return key


def test_login_replay_logout_duplicate(client):
    key = register(client)
    body = credential(options(client, "login"), key, "login", count=2)
    r = client.post("/api/auth/passkeys/login/verify", json=body)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["user"]["username"] == "admin"
    auth = {"Authorization": f"Bearer {data['access_token']}"}
    assert client.get("/api/me", headers=auth).status_code == 200
    assert client.post("/api/auth/passkeys/login/verify", json=body).status_code == 401
    assert client.post("/api/auth/logout", headers=auth).status_code == 200
    assert client.get("/api/me", headers=auth).status_code == 401
    opts = options(client, "register")
    assert opts["public_key"]["excludeCredentials"]
    assert (
        client.post(
            "/api/auth/passkeys/register/verify",
            headers=headers(client),
            json=credential(opts, key, "register"),
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "failure",
    [
        "origin",
        "uv",
        "signature",
        "challenge",
        "rp",
        "handle",
        "counter",
        "disabled",
        "unknown",
        "expired",
    ],
)
def test_invalid_assertion(client, failure):
    key = register(client)
    opts = options(client, "login")
    if failure == "challenge":
        opts["public_key"]["challenge"] = b64(b"wrong")
    body = credential(
        opts,
        key,
        "login",
        count=1 if failure == "counter" else 2,
        origin="https://evil.test" if failure == "origin" else "http://localhost:5173",
        flags=1 if failure == "uv" else 5,
        rp="evil.test" if failure == "rp" else "localhost",
        handle=2 if failure == "handle" else 1,
    )
    if failure == "signature":
        body["credential"]["response"]["signature"] = b64(b"invalid")
    if failure == "unknown":
        body["credential"]["id"] = b64(b"unknown")
    if failure == "expired":
        from app.passkeys import challenge_key

        client.app.state.cache.delete(challenge_key(opts["ticket"]))
    if failure == "disabled":
        with client.app.state.sessions() as db:
            db.get(User, 1).status = "disabled"
            db.commit()
    r = client.post("/api/auth/passkeys/login/verify", json=body)
    assert r.status_code == 401, r.text


def test_registration_binding_validation_uv(client):
    assert client.post("/api/auth/passkeys/register/options").status_code == 401
    key = ec.generate_private_key(ec.SECP256R1())
    for failure in ("user", "uv", "origin", "purpose"):
        opts = options(client, "login" if failure == "purpose" else "register")
        body = credential(
            opts,
            key,
            "register",
            flags=1 if failure == "uv" else 5,
            origin="https://evil.test" if failure == "origin" else "http://localhost:5173",
        )
        assert (
            client.post(
                "/api/auth/passkeys/register/verify",
                headers=headers(client, 2 if failure == "user" else 1),
                json=body,
            ).status_code
            == 401
        )
    assert client.post("/api/auth/passkeys/login/verify", json={}).status_code == 422
    opts = options(client, "login")
    assert (
        client.post(
            "/api/auth/passkeys/login/verify", json={"ticket": opts["ticket"], "credential": {}}
        ).status_code
        == 401
    )


def test_rate_limit_and_cache_failure(client):
    for _ in range(60):
        assert client.post("/api/auth/passkeys/login/options").status_code == 200
    assert client.post("/api/auth/passkeys/login/options").status_code == 429
    client.app.state.cache = None
    assert client.post("/api/auth/passkeys/login/options").status_code == 503


def test_email_delivery(client, monkeypatch):
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


def test_concurrent_passkey_challenge_consumption(client):
    from concurrent.futures import ThreadPoolExecutor

    key = register(client)
    body = credential(options(client, "login"), key, "login", count=2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: client.post("/api/auth/passkeys/login/verify", json=body).status_code,
                range(2),
            )
        )
    assert sorted(results) == [200, 401]


def test_email_daily_limit(client):
    from datetime import UTC, datetime

    ticket = login(client)
    client.app.state.settings.smtp_host = "smtp.example.test"
    client.app.state.cache.set(f"auth:send:daily:1:{datetime.now(UTC).date()}", 20, ex=86400)
    response = client.post("/api/auth/send-code", json={"ticket": ticket})
    assert response.status_code == 429
    assert "Daily" in response.json()["message"]
