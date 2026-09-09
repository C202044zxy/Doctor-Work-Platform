import fakeredis
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError
from sqlalchemy import func, select

from app.config import Settings
from app.main import create_app
from app.models import Allergy, AuditLog, Department
from app.seed import seed


@pytest.fixture
def client(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.delenv("REDIS_URL", raising=False)
    command.upgrade(Config("alembic.ini"), "head")
    seed()
    seed()  # Seeding must be safe to repeat.
    app = create_app(Settings(database_url=url, redis_url=None))
    with TestClient(app) as client:
        yield client


def test_patient_lifecycle_and_audit(client):
    departments = client.get("/api/departments").json()["data"]
    assert len(departments) == 2
    body = {"name": "  Demo Patient  ", "department_id": departments[0]["id"], "notes": "Synthetic"}
    created = client.post("/api/patients", json=body)
    assert created.status_code == 201
    patient = created.json()["data"]
    assert patient["name"] == "Demo Patient"
    pid = patient["id"]
    assert client.get(f"/api/patients/{pid}").json()["data"] == patient
    assert client.get("/api/patients?q=Demo").json()["total"] == 1
    assert client.get("/api/patients?q=Missing").json()["total"] == 0
    assert client.get("/api/patients?q=%25").json()["total"] == 0
    assert client.get("/api/patients?offset=1").json()["data"] == []
    with client.app.state.sessions() as db:
        db.add(Allergy(patient_id=pid, substance="Demo allergen"))
        db.commit()
    assert client.delete(f"/api/patients/{pid}").status_code == 204
    assert client.get(f"/api/patients/{pid}").status_code == 404
    assert client.delete(f"/api/patients/{pid}").status_code == 404
    with client.app.state.sessions() as db:
        assert list(db.scalars(select(AuditLog.action).order_by(AuditLog.id))) == [
            "patient.create",
            "patient.delete",
        ]
        assert db.scalar(select(func.count()).select_from(Allergy)) == 0


@pytest.mark.parametrize(
    "body, status",
    [
        ({"name": " ", "department_id": 1}, 422),
        ({"name": "Demo", "department_id": 999}, 404),
        ({"name": "Demo", "department_id": 1, "notes": "x" * 2001}, 422),
    ],
)
def test_invalid_patient(client, body, status):
    response = client.post("/api/patients", json=body)
    assert response.status_code == status
    assert "error" in response.json()
    assert client.get("/api/patients").json()["total"] == 0


def test_health_dependencies(client, monkeypatch):
    assert client.get("/api/health/live").status_code == 200
    assert client.get("/api/health/ready").json()["checks"] == {
        "database": "ok",
        "redis": "disabled",
    }
    cache = fakeredis.FakeRedis()
    client.app.state.cache = cache
    assert client.get("/api/health/ready").json()["checks"]["redis"] == "ok"

    def unavailable():
        raise ConnectionError("offline")

    monkeypatch.setattr(cache, "ping", unavailable)
    assert client.get("/api/health/ready").status_code == 503
    client.app.state.cache = None
    Department.__table__.drop(client.app.state.engine)
    assert client.get("/api/health/ready").status_code == 503
    assert client.get("/api/departments").json() == {"error": {"message": "Database unavailable"}}


def test_data_survives_app_restart(client):
    client.post("/api/patients", json={"name": "Persistent Demo", "department_id": 1})
    app = create_app(Settings(database_url=str(client.app.state.engine.url), redis_url=None))
    with TestClient(app) as restarted:
        assert restarted.get("/api/patients").json()["data"][0]["name"] == "Persistent Demo"


def test_pagination_validation(client):
    assert client.get("/api/patients?limit=101").status_code == 422
    assert client.get("/api/patients?offset=-1").status_code == 422
