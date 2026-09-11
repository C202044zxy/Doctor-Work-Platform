from datetime import UTC, datetime, timedelta

import fakeredis
import jwt
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import code_key, hash_password, issue_token, store_verification_code, ticket_key
from app.config import Settings
from app.grants import expire_grants
from app.main import create_app
from app.models import AuditLog, Department, Role, TempGrant, User
from app.seed import seed


@pytest.fixture
def client(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'auth.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    seed()
    app = create_app(Settings(database_url=url, redis_url=None, scheduler_enabled=True))
    app.state.cache = fakeredis.FakeRedis()
    with app.state.sessions() as db:
        roles = {r.name: r.id for r in db.scalars(select(Role))}
        departments = list(db.scalars(select(Department).order_by(Department.id)))
        for index, (name, role, dept) in enumerate(
            [
                ("admin", "admin", 0),
                ("senior", "senior", 0),
                ("junior", "junior", 1),
                ("outsider", "senior", 1),
            ],
            1,
        ):
            db.add(
                User(
                    id=index,
                    username=name,
                    name=name,
                    email=f"{name}@example.test",
                    password_hash=hash_password("test-password"),
                    role_id=roles[role],
                    department_id=departments[dept].id,
                )
            )
        db.commit()
    with TestClient(app) as client:
        yield client


def token(client, user_id=1):
    with client.app.state.sessions() as db:
        return issue_token(db.get(User, user_id), client.app.state.settings.jwt_secret)


def headers(client, user_id=1):
    return {"Authorization": f"Bearer {token(client, user_id)}"}


def login(client):
    response = client.post(
        "/api/auth/login", json={"username": "admin", "password": "test-password"}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert set(data) == {"ticket", "expires_in"}
    assert data["expires_in"] == 300
    assert 0 < client.app.state.cache.ttl(ticket_key(data["ticket"])) <= 300
    return data["ticket"]


def put_code(client, ticket):
    store_verification_code(
        client.app.state.cache, client.app.state.settings.jwt_secret, ticket, "123456"
    )


def test_auth_handshake_logout_and_disabled(client):
    ticket = login(client)
    put_code(client, ticket)
    cache = client.app.state.cache
    assert cache.get(code_key(1)) != b"123456"
    assert 0 < cache.ttl(code_key(1)) <= 300
    body = {"ticket": ticket, "code": "123456"}
    response = client.post("/api/auth/verify-code", json=body)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["expires_in"] == 7200
    claims = jwt.decode(
        data["access_token"], client.app.state.settings.jwt_secret, algorithms=["HS256"]
    )
    assert claims["title"] == "admin"
    assert claims["exp"] - claims["iat"] == 7200
    assert client.post("/api/auth/verify-code", json=body).status_code == 401
    auth = {"Authorization": f"Bearer {data['access_token']}"}
    assert client.get("/api/me", headers=auth).json()["data"]["title"] == "admin"
    assert client.post("/api/auth/logout", headers=auth).status_code == 200
    revoked = client.get("/api/me", headers=auth)
    missing = client.get("/api/me")
    claims["exp"] = datetime.now(UTC) - timedelta(seconds=1)
    expired = jwt.encode(claims, client.app.state.settings.jwt_secret, algorithm="HS256")
    expired_response = client.get("/api/me", headers={"Authorization": f"Bearer {expired}"})
    assert {r.status_code for r in (revoked, missing, expired_response)} == {401}
    assert len({r.json()["message"] for r in (revoked, missing, expired_response)}) == 3
    auth = headers(client)
    with client.app.state.sessions() as db:
        db.get(User, 1).status = "disabled"
        db.commit()
    assert client.get("/api/me", headers=auth).status_code == 401


def test_password_throttle_and_validation(client):
    for attempt in range(5):
        response = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert response.status_code == (429 if attempt == 4 else 401)
    assert (
        client.post(
            "/api/auth/login", json={"username": "admin", "password": "test-password"}
        ).status_code
        == 429
    )
    assert (
        client.post(
            "/api/auth/login", json={"username": "admin", "password": "密" * 30}
        ).status_code
        == 422
    )
    with client.app.state.sessions() as db:
        assert db.get(User, 1).password_hash.startswith("$2b$")


def test_code_failure_expiry_ticket_binding_and_attempt_limit(client):
    ticket = login(client)
    assert (
        client.post("/api/auth/verify-code", json={"ticket": ticket, "code": "123456"}).json()[
            "message"
        ]
        == "The code has expired"
    )
    put_code(client, ticket)
    other = login(client)
    assert (
        client.post("/api/auth/verify-code", json={"ticket": other, "code": "123456"}).status_code
        == 401
    )
    for _ in range(5):
        assert (
            client.post(
                "/api/auth/verify-code", json={"ticket": ticket, "code": "000000"}
            ).status_code
            == 401
        )
    assert client.app.state.cache.get(ticket_key(ticket)) is None
    assert (
        client.post("/api/auth/verify-code", json={"ticket": ticket, "code": "bad"}).status_code
        == 422
    )


def patient(client):
    response = client.post(
        "/api/patients",
        headers=headers(client),
        json={"name": "Synthetic", "gender": "unknown", "department": "General Medicine"},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["patient_no"]


def grant_body(number):
    return {
        "grantee_id": 3,
        "patient_no": number,
        "reason": "Consultation",
        "expire_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }


def test_grant_visibility_revoke_expiry_and_audit(client):
    number = patient(client)
    path = f"/api/patients/{number}"
    junior = headers(client, 3)
    assert client.get(path).status_code == 401
    assert client.get(path, headers=junior).status_code == 404
    assert client.get("/api/patients", headers=junior).json()["data"]["total"] == 0
    body = grant_body(number)
    response = client.post("/api/temp-grants", json=body, headers=headers(client, 2))
    assert response.status_code == 200, response.text
    grant_id = response.json()["data"]["id"]
    assert client.get(path, headers=junior).status_code == 200
    assert client.get("/api/patients", headers=junior).json()["data"]["total"] == 1
    filtered = client.get(
        f"/api/temp-grants?grantee_id=3&patient_no={number}&is_valid=true", headers=headers(client)
    )
    assert filtered.json()["data"]["total"] == 1
    assert (
        client.delete(f"/api/temp-grants/{grant_id}", headers=headers(client)).json()["data"][
            "is_valid"
        ]
        is False
    )
    assert client.get(path, headers=junior).status_code == 404
    response = client.post("/api/temp-grants", json=body, headers=headers(client))
    grant_id = response.json()["data"]["id"]
    with client.app.state.sessions() as db:
        db.get(TempGrant, grant_id).expire_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    # Expired grants stop authorizing before the scheduler runs.
    assert client.get(path, headers=junior).status_code == 404
    expire_grants(client.app.state.sessions)
    expire_grants(client.app.state.sessions)
    with client.app.state.sessions() as db:
        assert not db.get(TempGrant, grant_id).is_valid
        actions = list(db.scalars(select(AuditLog.action)))
        assert actions.count("temp_grant.create") == 2
        assert actions.count("temp_grant.expire") == 1
    assert len(client.app.state.scheduler.get_jobs()) == 1
    assert (
        client.app.state.scheduler.get_job("expire_temp_grants").trigger.interval.total_seconds()
        == 60
    )


def test_grant_permissions_not_found_validation_and_scope(client):
    number = patient(client)
    body = grant_body(number)
    assert client.post("/api/temp-grants", json=body, headers=headers(client, 3)).status_code == 403
    assert client.get("/api/temp-grants", headers=headers(client, 3)).status_code == 403
    assert client.post("/api/temp-grants", json=body, headers=headers(client, 4)).status_code == 404
    assert (
        client.post(
            "/api/temp-grants", json={**body, "grantee_id": 999}, headers=headers(client)
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/temp-grants", json={**body, "patient_no": "missing"}, headers=headers(client)
        ).status_code
        == 404
    )
    assert client.delete("/api/temp-grants/999", headers=headers(client)).status_code == 404
    for patch in (
        {"expire_at": datetime.now(UTC).isoformat()},
        {"expire_at": "2027-01-01T00:00:00"},
        {"reason": " "},
        {"reason": "x" * 501},
    ):
        assert (
            client.post(
                "/api/temp-grants", json={**body, **patch}, headers=headers(client)
            ).status_code
            == 422
        )
    assert client.get("/api/temp-grants?page=0", headers=headers(client)).status_code == 422


def test_invalid_tokens_redis_failure_and_health_alias(client):
    assert client.get("/api/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    assert client.get("/health").content == client.get("/api/health").content
    client.app.state.cache = None
    assert client.get("/api/me", headers=headers(client)).status_code == 503


def test_patient_allergy_scope_and_senior_grant_boundaries(client):
    number = patient(client)
    admin = headers(client)
    junior = headers(client, 3)
    response = client.post(
        f"/api/patients/{number}/allergies",
        headers=admin,
        json={
            "allergen": "PENICILLIN",
            "allergy_type": "drug",
            "severity": "severe",
            "recorded_at": "2026-09-11",
        },
    )
    allergy_id = response.json()["data"]["id"]
    assert client.get(f"/api/patients/{number}/allergies", headers=junior).status_code == 404
    assert (
        client.patch(
            f"/api/allergies/{allergy_id}", headers=junior, json={"severity": "mild"}
        ).status_code
        == 404
    )
    assert client.delete(f"/api/allergies/{allergy_id}", headers=junior).status_code == 404
    assert (
        client.post(
            "/api/patients",
            headers=junior,
            json={
                "name": "Outside",
                "gender": "unknown",
                "department": "General Medicine",
            },
        ).status_code
        == 403
    )
    response = client.post("/api/temp-grants", headers=admin, json=grant_body(number))
    grant_id = response.json()["data"]["id"]
    assert (
        client.delete(f"/api/temp-grants/{grant_id}", headers=headers(client, 4)).status_code == 404
    )
    assert client.get("/api/temp-grants", headers=headers(client, 4)).json()["data"]["total"] == 0
    assert client.get(f"/api/patients/{number}/allergies", headers=junior).status_code == 200


def test_concurrent_code_consumption_only_issues_one_token(client):
    from concurrent.futures import ThreadPoolExecutor

    ticket = login(client)
    put_code(client, ticket)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda _: client.post(
                    "/api/auth/verify-code",
                    json={
                        "ticket": ticket,
                        "code": "123456",
                    },
                ),
                range(2),
            )
        )
    assert sorted(response.status_code for response in responses) == [200, 401]


def test_health_dependency_failure_still_returns_200(client, monkeypatch):
    from redis.exceptions import ConnectionError

    def unavailable():
        raise ConnectionError("Unavailable")

    monkeypatch.setattr(client.app.state.cache, "ping", unavailable)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["data"]["redis"] == "down"
    assert response.content == client.get("/api/health").content
