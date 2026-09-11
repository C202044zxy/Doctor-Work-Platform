from datetime import UTC, datetime

import fakeredis
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError
from sqlalchemy import DateTime, TypeDecorator, func, select

from app.config import Settings
from app.crypto import decrypt
from app.main import create_app
from app.models import Allergy, AuditLog, Department, Patient
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


def current_year():
    return datetime.now(UTC).year


def create_patient(client, **overrides):
    body = {"name": "Demo Patient", "department_id": 1, "notes": "Synthetic"}
    body.update(overrides)
    response = client.post("/api/patients", json=body)
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_patient_lifecycle_and_audit(client):
    departments = client.get("/api/departments").json()["data"]
    assert len(departments) == 2
    patient = create_patient(client, name="  Demo Patient  ", department_id=departments[0]["id"])
    assert patient["name"] == "Demo Patient"
    assert patient["patient_no"] == f"P{current_year()}0001"
    assert patient["symptom_tags"] == []
    assert patient["phone"] is None
    assert patient["id_card"] is None
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


def test_patient_numbers_are_generated_and_unique(client):
    year = current_year()
    numbers = [create_patient(client, name=f"Patient {index}")["patient_no"] for index in range(3)]
    assert numbers == [f"P{year}0001", f"P{year}0002", f"P{year}0003"]
    assert len(set(numbers)) == 3


def test_combined_search_and_ands_every_filter(client):
    target = create_patient(client, name="赵雷", symptom_tags=["胸痛"], admitted_at="2026-08-15")
    create_patient(client, name="赵敏", symptom_tags=["发热"], admitted_at="2026-08-20")
    create_patient(client, name="李雷", symptom_tags=["胸痛"], admitted_at="2026-07-20")
    create_patient(client, name="王强", symptom_tags=["胸痛"], admitted_at="2026-08-05")

    combined = client.get(
        "/api/patients",
        params={
            "q": "赵",
            "symptom_tag": "胸痛",
            "admitted_from": "2026-08-01",
            "admitted_to": "2026-09-01",
        },
    ).json()
    assert combined["total"] == 1
    assert combined["data"][0]["patient_no"] == target["patient_no"]

    assert client.get("/api/patients", params={"q": "赵"}).json()["total"] == 2
    by_number = client.get("/api/patients", params={"patient_no": target["patient_no"]}).json()
    assert by_number["total"] == 1
    assert by_number["data"][0]["id"] == target["id"]
    # patient_no is an exact match, not a prefix match.
    assert (
        client.get("/api/patients", params={"patient_no": f"P{current_year()}000"}).json()["total"]
        == 0
    )
    assert client.get("/api/patients", params={"symptom_tag": "胸痛"}).json()["total"] == 3
    # A tag match is exact: "胸" must not match the tag "胸痛".
    assert client.get("/api/patients", params={"symptom_tag": "胸"}).json()["total"] == 0
    window = client.get(
        "/api/patients", params={"admitted_from": "2026-08-01", "admitted_to": "2026-09-01"}
    ).json()
    assert window["total"] == 3
    assert client.get("/api/patients").json()["total"] == 4


def test_admission_range_validation(client):
    response = client.get(
        "/api/patients", params={"admitted_from": "2026-09-01", "admitted_to": "2026-08-01"}
    )
    assert response.status_code == 422
    assert "admitted_from" in response.json()["error"]["message"]


def test_default_order_is_created_at_descending(client):
    ids = [create_patient(client, name=f"Patient {index}")["id"] for index in range(3)]
    page = client.get("/api/patients").json()
    assert page["total"] == 3
    assert [row["id"] for row in page["data"]] == list(reversed(ids))
    first = client.get("/api/patients", params={"limit": 2}).json()
    assert [row["id"] for row in first["data"]] == list(reversed(ids))[:2]
    second = client.get("/api/patients", params={"limit": 2, "offset": 2}).json()
    assert [row["id"] for row in second["data"]] == list(reversed(ids))[2:]
    assert second["total"] == 3


def test_identifiers_are_encrypted_at_rest_and_masked_in_the_api(client):
    patient = create_patient(
        client, name="Masked Demo", phone="13800001234", id_card="110101199003071234"
    )
    assert patient["phone"] == "138****1234"
    assert patient["id_card"] == "110101********1234"
    assert client.get(f"/api/patients/{patient['id']}").json()["data"]["phone"] == "138****1234"
    listed = client.get("/api/patients", params={"q": "Masked"}).json()["data"][0]
    assert listed["phone"] == "138****1234"
    assert "13800001234" not in str(listed)
    with client.app.state.sessions() as db:
        stored = db.get(Patient, patient["id"])
        assert stored.phone_enc != "13800001234"
        assert "13800001234" not in stored.phone_enc
        assert decrypt(stored.phone_enc) == "13800001234"
        assert decrypt(stored.id_card_enc) == "110101199003071234"


def test_validation_error_names_the_missing_field(client):
    missing = client.post("/api/patients", json={"department_id": 1})
    assert missing.status_code == 422
    assert missing.json()["error"]["fields"] == ["name"]
    assert "name" in missing.json()["error"]["message"]

    blank = client.post("/api/patients", json={"name": "   ", "department_id": 1})
    assert blank.status_code == 422
    assert "name" in blank.json()["error"]["message"]
    assert client.get("/api/patients").json()["total"] == 0


def test_patient_update(client):
    patient = create_patient(client, name="Before", notes="old")
    updated = client.patch(
        f"/api/patients/{patient['id']}",
        json={
            "name": "After",
            "notes": "new",
            "phone": "13800001234",
            "symptom_tags": ["胸痛", "胸痛", "发热"],
            "admitted_at": "2026-08-15",
        },
    )
    assert updated.status_code == 200
    data = updated.json()["data"]
    assert data["name"] == "After"
    assert data["notes"] == "new"
    assert data["phone"] == "138****1234"
    assert data["symptom_tags"] == ["胸痛", "发热"]
    assert data["admitted_at"] == "2026-08-15"
    assert data["patient_no"] == patient["patient_no"]
    assert client.get(f"/api/patients/{patient['id']}").json()["data"] == data

    cleared = client.patch(f"/api/patients/{patient['id']}", json={"phone": None}).json()["data"]
    assert cleared["phone"] is None

    assert client.patch("/api/patients/9999", json={"name": "Ghost"}).status_code == 404
    assert (
        client.patch(f"/api/patients/{patient['id']}", json={"department_id": 999}).status_code
        == 404
    )
    assert client.patch(f"/api/patients/{patient['id']}", json={"name": None}).status_code == 422
    with client.app.state.sessions() as db:
        assert list(db.scalars(select(AuditLog.action).order_by(AuditLog.id))) == [
            "patient.create",
            "patient.update",
            "patient.update",
        ]


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


def test_swagger_documents_every_patient_field(client):
    schema = client.get("/openapi.json").json()
    properties = schema["components"]["schemas"]["PatientRead"]["properties"]
    for field in (
        "id",
        "patient_no",
        "name",
        "department_id",
        "notes",
        "phone",
        "id_card",
        "symptom_tags",
        "admitted_at",
        "created_at",
    ):
        description = properties[field]["description"]
        assert any("一" <= char <= "鿿" for char in description), field
        assert any(char.isascii() and char.isalpha() for char in description), field
    assert properties["patient_no"]["examples"] == ["P20260001"]
    assert properties["phone"]["examples"] == ["138****1234"]

    list_parameters = {
        parameter["name"]: parameter
        for parameter in schema["paths"]["/api/patients"]["get"]["parameters"]
    }
    assert set(list_parameters) == {
        "q",
        "patient_no",
        "symptom_tag",
        "admitted_from",
        "admitted_to",
        "offset",
        "limit",
    }
    for parameter in list_parameters.values():
        description = parameter["description"]
        assert any("一" <= char <= "鿿" for char in description), parameter["name"]
        assert any(char.isascii() and char.isalpha() for char in description), parameter["name"]

    patient_path = schema["paths"]["/api/patients/{patient_id}"]
    assert set(patient_path) == {"get", "patch", "delete"}


class _WholeSecondDateTime(TypeDecorator):
    """Reproduce MySQL's DATETIME precision, which keeps whole seconds only."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return value.replace(microsecond=0) if value is not None else value


def test_write_response_matches_what_the_database_stores(client, monkeypatch):
    # MySQL DATETIME has no fractional seconds while SQLite keeps microseconds, so
    # echoing the Python-side default would return a value the next read cannot match.
    monkeypatch.setattr(Patient.__table__.c.created_at, "type", _WholeSecondDateTime())
    patient = create_patient(client, name="Echo Test")
    assert client.get(f"/api/patients/{patient['id']}").json()["data"] == patient
    updated = client.patch(f"/api/patients/{patient['id']}", json={"name": "Echo Again"})
    assert updated.status_code == 200
    assert client.get(f"/api/patients/{patient['id']}").json()["data"] == updated.json()["data"]
