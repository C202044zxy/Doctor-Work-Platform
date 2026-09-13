"""Run from backend/: uv run python ../scripts/verify_sprint1.py.

Uses configured MySQL and real Redis, creates synthetic records, waits for the
actual minute scheduler, then removes only those records. Does not exercise SMTP.
"""

import secrets
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.auth import hash_password, store_verification_code
from app.config import Settings
from app.main import create_app
from app.models import AuditLog, Department, Patient, Role, TempGrant, User

settings = Settings()
assert settings.database_url.startswith("mysql+pymysql:"), "This check requires MySQL"
app = create_app(settings)
suffix = secrets.token_hex(6)
password = secrets.token_urlsafe(24)
user_ids = []
patient_id = None
try:
    with app.state.sessions() as db:
        departments = list(db.scalars(select(Department).order_by(Department.id)))
        roles = {role.name: role.id for role in db.scalars(select(Role))}
        for index, title in enumerate(("admin", "junior")):
            user = User(
                username=f"verify_{title}_{suffix}",
                name="Synthetic verification",
                email=f"verify_{title}_{suffix}@example.test",
                password_hash=hash_password(password),
                role_id=roles[title],
                department_id=departments[index].id,
            )
            db.add(user)
            db.flush()
            user_ids.append(user.id)
        db.commit()
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.json()["data"] == {"db": "ok", "redis": "ok"}
        assert health.content == client.get("/api/health").content
        tokens = []
        for title in ("admin", "junior"):
            response = client.post(
                "/api/auth/login",
                json={"username": f"verify_{title}_{suffix}", "password": password},
            )
            assert response.status_code == 200, response.text
            ticket = response.json()["data"]["ticket"]
            code = f"{secrets.randbelow(1_000_000):06d}"
            store_verification_code(app.state.cache, settings.jwt_secret, ticket, code)
            response = client.post("/api/auth/verify-code", json={"ticket": ticket, "code": code})
            assert response.status_code == 200, response.text
            tokens.append({"Authorization": "Bearer " + response.json()["data"]["access_token"]})
        admin, junior = tokens
        response = client.post(
            "/api/patients",
            headers=admin,
            json={
                "name": "Synthetic verification",
                "gender": "unknown",
                "department": departments[0].name,
            },
        )
        assert response.status_code == 200, response.text
        number = response.json()["data"]["patient_no"]
        with app.state.sessions() as db:
            patient_id = db.scalar(select(Patient.id).where(Patient.patient_no == number))
        path = f"/api/patients/{number}"
        assert client.get(path, headers=junior).status_code == 404
        response = client.post(
            "/api/temp-grants",
            headers=admin,
            json={
                "grantee_id": user_ids[1],
                "patient_no": number,
                "reason": "Synthetic integration check",
                "expire_at": (datetime.now(UTC) + timedelta(seconds=10)).isoformat(),
            },
        )
        assert response.status_code == 200, response.text
        grant_id = response.json()["data"]["id"]
        assert client.get(path, headers=junior).status_code == 200
        print(
            "MySQL + Redis: login, JWT and grant access passed; waiting for minute expiry scan",
            flush=True,
        )
        deadline = time.monotonic() + 75
        while time.monotonic() < deadline:
            with app.state.sessions() as db:
                if not db.get(TempGrant, grant_id).is_valid:
                    break
            time.sleep(2)
        else:
            raise AssertionError("Scheduler did not expire the grant within 75 seconds")
        assert client.get(path, headers=junior).status_code == 404
        with app.state.sessions() as db:
            actions = list(
                db.scalars(select(AuditLog.action).where(AuditLog.patient_id == patient_id))
            )
            assert actions.count("temp_grant.create") == 1
            assert actions.count("temp_grant.expire") == 1
        for auth in tokens:
            assert client.post("/api/auth/logout", headers=auth).status_code == 200
            assert client.get("/api/me", headers=auth).status_code == 401
        print(
            "PASS: scheduled expiry, single audit event, lost access and JWT logout revocation",
            flush=True,
        )
finally:
    with app.state.sessions() as db:
        if patient_id is not None:
            db.execute(delete(TempGrant).where(TempGrant.patient_id == patient_id))
            db.execute(delete(AuditLog).where(AuditLog.patient_id == patient_id))
            db.execute(delete(Patient).where(Patient.id == patient_id))
        if user_ids:
            db.execute(delete(User).where(User.id.in_(user_ids)))
        db.commit()
    app.state.engine.dispose()
