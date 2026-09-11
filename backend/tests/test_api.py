from datetime import UTC, date, datetime

import fakeredis
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import DateTime, TypeDecorator, func, select

from app.allergies import get_patient_allergens
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
    body = {"name": "Demo Patient", "gender": "male", "department": "General Medicine"}
    body.update(overrides)
    response = client.post("/api/patients", json=body)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def stored_patient(client, patient_no):
    with client.app.state.sessions() as db:
        return db.scalar(select(Patient).where(Patient.patient_no == patient_no))


def add_allergy(client, patient_no, **overrides):
    body = {
        "allergen": "PENICILLIN",
        "allergy_type": "drug",
        "severity": "severe",
        "recorded_at": "2026-08-01",
    }
    body.update(overrides)
    response = client.post(f"/api/patients/{patient_no}/allergies", json=body)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_envelope_shape_on_success_and_error(client):
    body = client.get("/api/departments").json()
    assert body["code"] == 0
    assert body["message"] == "ok"
    assert isinstance(body["data"], list)

    missing = client.get("/api/patients/P20269999")
    assert missing.status_code == 404
    assert missing.json() == {"code": 404, "message": "Patient not found", "data": None}


def test_patient_lifecycle_and_audit(client):
    departments = client.get("/api/departments").json()["data"]
    assert [row["name"] for row in departments] == ["General Medicine", "Cardiology"]
    patient = create_patient(client, name="  Demo Patient  ", department=departments[0]["name"])
    assert patient["name"] == "Demo Patient"
    assert patient["patient_no"] == f"P{current_year()}0001"
    assert patient["department"] == "General Medicine"
    assert patient["gender"] == "male"
    assert patient["symptom_tags"] == []
    assert patient["phone"] is None
    assert patient["phone_masked"] is None
    assert patient["id_card_masked"] is None
    assert patient["allergy_count"] == 0
    assert patient["has_severe_allergy"] is False
    assert patient["allergies"] == []
    number = patient["patient_no"]
    assert client.get(f"/api/patients/{number}").json()["data"] == patient

    with client.app.state.sessions() as db:
        row = db.scalar(select(Patient).where(Patient.patient_no == number))
        db.add(
            Allergy(
                patient_id=row.id,
                allergen="PENICILLIN",
                allergy_type="drug",
                severity="severe",
                recorded_at=date(2026, 8, 1),
            )
        )
        db.commit()

    assert client.delete(f"/api/patients/{number}").json() == {
        "code": 0,
        "message": "ok",
        "data": {},
    }
    assert client.get(f"/api/patients/{number}").status_code == 404
    assert client.delete(f"/api/patients/{number}").status_code == 404
    assert client.get("/api/patients", params={"name": "Demo"}).json()["data"]["total"] == 0
    with client.app.state.sessions() as db:
        assert list(db.scalars(select(AuditLog.action).order_by(AuditLog.id))) == [
            "patient.create",
            "patient.delete",
        ]
        # Soft delete: the row and its allergies stay in the table, reads just filter them.
        row = db.scalar(select(Patient).where(Patient.patient_no == number))
        assert row is not None and row.deleted_at is not None
        assert db.scalar(select(func.count()).select_from(Allergy)) == 1


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
            "name": "赵",
            "symptom_tags": "胸痛",
            "admitted_from": "2026-08-01",
            "admitted_to": "2026-09-01",
        },
    ).json()["data"]
    assert combined["total"] == 1
    assert combined["items"][0]["patient_no"] == target["patient_no"]

    assert client.get("/api/patients", params={"name": "赵"}).json()["data"]["total"] == 2
    by_number = client.get("/api/patients", params={"patient_no": target["patient_no"]}).json()[
        "data"
    ]
    assert by_number["total"] == 1
    assert by_number["items"][0]["patient_no"] == target["patient_no"]
    # patient_no is an exact match, not a prefix match.
    assert (
        client.get("/api/patients", params={"patient_no": f"P{current_year()}000"}).json()["data"][
            "total"
        ]
        == 0
    )
    assert client.get("/api/patients", params={"symptom_tags": "胸痛"}).json()["data"]["total"] == 3
    # Repeating the parameter matches any of the tags.
    assert (
        client.get(
            "/api/patients", params=[("symptom_tags", "发热"), ("symptom_tags", "胸痛")]
        ).json()["data"]["total"]
        == 4
    )
    # A tag match is exact: "胸" must not match the tag "胸痛".
    assert client.get("/api/patients", params={"symptom_tags": "胸"}).json()["data"]["total"] == 0
    window = client.get(
        "/api/patients", params={"admitted_from": "2026-08-01", "admitted_to": "2026-09-01"}
    ).json()["data"]
    assert window["total"] == 3
    assert client.get("/api/patients").json()["data"]["total"] == 4


def test_admission_range_validation(client):
    response = client.get(
        "/api/patients", params={"admitted_from": "2026-09-01", "admitted_to": "2026-08-01"}
    )
    assert response.status_code == 422
    assert "admitted_from" in response.json()["message"]


def test_default_order_is_created_at_descending(client):
    numbers = [create_patient(client, name=f"Patient {index}")["patient_no"] for index in range(3)]
    page = client.get("/api/patients").json()["data"]
    assert page["total"] == 3
    assert page["page"] == 1
    assert page["size"] == 20
    assert [row["patient_no"] for row in page["items"]] == list(reversed(numbers))
    first = client.get("/api/patients", params={"size": 2}).json()["data"]
    assert [row["patient_no"] for row in first["items"]] == list(reversed(numbers))[:2]
    second = client.get("/api/patients", params={"size": 2, "page": 2}).json()["data"]
    assert [row["patient_no"] for row in second["items"]] == list(reversed(numbers))[2:]
    assert second["total"] == 3


def test_identifiers_are_encrypted_at_rest_and_masked_in_the_api(client):
    patient = create_patient(
        client, name="Masked Demo", phone="13800001234", id_card="110101199003071234"
    )
    assert patient["phone_masked"] == "138****1234"
    assert patient["phone"] == "138****1234"
    assert patient["id_card_masked"] == "110101********1234"
    assert patient["id_card"] == "110101********1234"
    number = patient["patient_no"]
    detail = client.get(f"/api/patients/{number}").json()["data"]
    assert detail["phone_masked"] == "138****1234"
    listed = client.get("/api/patients", params={"name": "Masked"}).json()["data"]["items"][0]
    assert listed["phone_masked"] == "138****1234"
    assert "13800001234" not in str(listed)
    stored = stored_patient(client, number)
    assert stored.phone_enc != "13800001234"
    assert "13800001234" not in stored.phone_enc
    assert decrypt(stored.phone_enc) == "13800001234"
    assert decrypt(stored.id_card_enc) == "110101199003071234"


def test_validation_error_names_the_missing_field(client):
    missing = client.post("/api/patients", json={"gender": "male", "department": "Cardiology"})
    assert missing.status_code == 422
    assert missing.json()["code"] == 422
    assert "name" in missing.json()["message"]

    blank = client.post(
        "/api/patients", json={"name": "   ", "gender": "male", "department": "Cardiology"}
    )
    assert blank.status_code == 422
    assert "name" in blank.json()["message"]

    bad_gender = client.post(
        "/api/patients", json={"name": "Demo", "gender": "?", "department": "Cardiology"}
    )
    assert bad_gender.status_code == 422
    assert "gender" in bad_gender.json()["message"]
    assert client.get("/api/patients").json()["data"]["total"] == 0


def test_patient_update(client):
    patient = create_patient(client, name="Before", notes="old")
    number = patient["patient_no"]
    updated = client.patch(
        f"/api/patients/{number}",
        json={
            "name": "After",
            "gender": "female",
            "notes": "new",
            "phone": "13800001234",
            "symptom_tags": ["胸痛", "胸痛", "发热"],
            "admitted_at": "2026-08-15",
            "department": "Cardiology",
        },
    )
    assert updated.status_code == 200
    data = updated.json()["data"]
    assert data["name"] == "After"
    assert data["gender"] == "female"
    assert data["department"] == "Cardiology"
    assert data["notes"] == "new"
    assert data["phone_masked"] == "138****1234"
    assert data["symptom_tags"] == ["胸痛", "发热"]
    assert data["admitted_at"] == "2026-08-15"
    assert data["patient_no"] == number
    assert client.get(f"/api/patients/{number}").json()["data"] == data

    cleared = client.patch(f"/api/patients/{number}", json={"phone": None}).json()["data"]
    assert cleared["phone_masked"] is None

    assert client.patch("/api/patients/P20269999", json={"name": "Ghost"}).status_code == 404
    assert (
        client.patch(f"/api/patients/{number}", json={"department": "Nowhere"}).status_code == 404
    )
    assert client.patch(f"/api/patients/{number}", json={"name": None}).status_code == 422
    with client.app.state.sessions() as db:
        assert list(db.scalars(select(AuditLog.action).order_by(AuditLog.id))) == [
            "patient.create",
            "patient.update",
            "patient.update",
        ]


@pytest.mark.parametrize(
    "body, status",
    [
        ({"name": " ", "gender": "male", "department": "General Medicine"}, 422),
        ({"name": "Demo", "gender": "male", "department": "Nowhere"}, 404),
        (
            {
                "name": "Demo",
                "gender": "male",
                "department": "General Medicine",
                "notes": "x" * 2001,
            },
            422,
        ),
    ],
)
def test_invalid_patient(client, body, status):
    response = client.post("/api/patients", json=body)
    assert response.status_code == status
    assert response.json()["code"] == status
    assert client.get("/api/patients").json()["data"]["total"] == 0


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
        raise RedisConnectionError("offline")

    monkeypatch.setattr(cache, "ping", unavailable)
    assert client.get("/api/health/ready").status_code == 503
    client.app.state.cache = None
    Department.__table__.drop(client.app.state.engine)
    assert client.get("/api/health/ready").status_code == 503
    assert client.get("/api/departments").json() == {
        "code": 503,
        "message": "Database unavailable",
        "data": None,
    }


def test_data_survives_app_restart(client):
    client.post(
        "/api/patients",
        json={"name": "Persistent Demo", "gender": "unknown", "department": "General Medicine"},
    )
    app = create_app(Settings(database_url=str(client.app.state.engine.url), redis_url=None))
    with TestClient(app) as restarted:
        items = restarted.get("/api/patients").json()["data"]["items"]
        assert items[0]["name"] == "Persistent Demo"


def test_pagination_validation(client):
    assert client.get("/api/patients?size=101").status_code == 422
    assert client.get("/api/patients?page=0").status_code == 422


def test_swagger_documents_every_patient_field(client):
    schema = client.get("/openapi.json").json()
    properties = schema["components"]["schemas"]["PatientDetail"]["properties"]
    for field in (
        "patient_no",
        "name",
        "gender",
        "birth_date",
        "phone_masked",
        "department",
        "symptom_tags",
        "allergy_count",
        "has_severe_allergy",
        "admitted_at",
        "notes",
        "created_at",
        "id_card_masked",
        "allergies",
        "histories",
        "groups",
    ):
        description = properties[field]["description"]
        assert any("一" <= char <= "鿿" for char in description), field
        assert any(char.isascii() and char.isalpha() for char in description), field
    assert properties["patient_no"]["examples"] == ["P20260001"]
    assert properties["phone_masked"]["examples"] == ["138****1234"]
    assert properties["id_card_masked"]["examples"] == ["110101********1234"]

    allergy_properties = schema["components"]["schemas"]["AllergyRead"]["properties"]
    assert allergy_properties["allergen"]["examples"] == ["PENICILLIN"]
    for field in ("allergen", "allergy_type", "severity", "reaction", "recorded_at"):
        description = allergy_properties[field]["description"]
        assert any("一" <= char <= "鿿" for char in description), field
        assert any(char.isascii() and char.isalpha() for char in description), field

    list_parameters = {
        parameter["name"]: parameter
        for parameter in schema["paths"]["/api/patients"]["get"]["parameters"]
    }
    assert set(list_parameters) == {
        "name",
        "patient_no",
        "symptom_tags",
        "admitted_from",
        "admitted_to",
        "page",
        "size",
    }
    for parameter in list_parameters.values():
        description = parameter["description"]
        assert any("一" <= char <= "鿿" for char in description), parameter["name"]
        assert any(char.isascii() and char.isalpha() for char in description), parameter["name"]

    patient_path = schema["paths"]["/api/patients/{patient_no}"]
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
    number = patient["patient_no"]
    assert client.get(f"/api/patients/{number}").json()["data"] == patient
    updated = client.patch(f"/api/patients/{number}", json={"name": "Echo Again"})
    assert updated.status_code == 200
    assert client.get(f"/api/patients/{number}").json()["data"] == updated.json()["data"]


def test_allergen_dictionary_covers_the_required_families(client):
    entries = client.get("/api/allergens").json()["data"]
    codes = {entry["code"] for entry in entries}
    assert {"PENICILLIN", "SULFONAMIDE", "CEPHALOSPORIN", "ASPIRIN", "CONTRAST_MEDIA"} <= codes
    assert all(entry["name"] for entry in entries)


def test_custom_allergen_joins_the_dictionary(client):
    """A code outside the five families is listed once it has been recorded."""
    entries = client.get("/api/allergens").json()["data"]
    assert [entry["code"] for entry in entries] == [
        "PENICILLIN",
        "SULFONAMIDE",
        "CEPHALOSPORIN",
        "ASPIRIN",
        "CONTRAST_MEDIA",
    ]

    patient = create_patient(client, name="Dictionary Demo")
    add_allergy(client, patient["patient_no"], allergen="latex", allergy_type="other")

    entries = client.get("/api/allergens").json()["data"]
    assert [entry["code"] for entry in entries] == [
        "PENICILLIN",
        "SULFONAMIDE",
        "CEPHALOSPORIN",
        "ASPIRIN",
        "CONTRAST_MEDIA",
        "LATEX",
    ]
    assert next(entry for entry in entries if entry["code"] == "LATEX")["name"] == "LATEX"


def test_patient_detail_carries_allergies_for_the_warning_banner(client):
    patient = create_patient(client, name="Banner Demo")
    number = patient["patient_no"]
    add_allergy(client, number, allergen="PENICILLIN", severity="severe")
    add_allergy(
        client, number, allergen="SULFONAMIDE", severity="moderate", recorded_at="2026-08-02"
    )

    detail = client.get(f"/api/patients/{number}").json()["data"]
    assert [item["allergen"] for item in detail["allergies"]] == ["PENICILLIN", "SULFONAMIDE"]
    assert detail["allergy_count"] == 2
    assert detail["has_severe_allergy"] is True
    assert detail["allergies"][0]["severity"] == "severe"
    listed = client.get("/api/patients", params={"name": "Banner"}).json()["data"]["items"][0]
    assert listed["allergy_count"] == 2
    assert listed["has_severe_allergy"] is True

    assert client.get(f"/api/patients/{number}/allergies").json()["data"] == detail["allergies"]


def test_get_patient_allergens_is_the_shared_source(client):
    patient = create_patient(client, name="Shared Source")
    number = patient["patient_no"]
    add_allergy(client, number, allergen="ASPIRIN", allergy_type="drug", severity="mild")
    with client.app.state.sessions() as db:
        shared = get_patient_allergens(db, number)
    assert [(item.allergen, item.severity) for item in shared] == [("ASPIRIN", "mild")]
    with client.app.state.sessions() as db:
        assert get_patient_allergens(db, "P20269999") == []


def test_allergy_update_and_delete_audit(client):
    patient = create_patient(client, name="Allergy Audit")
    number = patient["patient_no"]
    first = add_allergy(client, number, allergen="PENICILLIN", severity="severe")
    second = add_allergy(
        client, number, allergen="SULFONAMIDE", severity="moderate", recorded_at="2026-08-02"
    )

    changed = client.patch(
        f"/api/allergies/{second['id']}", json={"severity": "mild", "reaction": "Rash"}
    )
    assert changed.status_code == 200
    assert changed.json()["data"]["severity"] == "mild"
    assert changed.json()["data"]["reaction"] == "Rash"

    assert client.delete(f"/api/allergies/{second['id']}").json()["code"] == 0
    assert client.delete(f"/api/allergies/{second['id']}").status_code == 404
    detail = client.get(f"/api/patients/{number}").json()["data"]
    assert [item["allergen"] for item in detail["allergies"]] == ["PENICILLIN"]

    with client.app.state.sessions() as db:
        actions = list(db.scalars(select(AuditLog.action).order_by(AuditLog.id)))
        assert actions == [
            "patient.create",
            "allergy.create",
            "allergy.create",
            "allergy.update",
            "allergy.delete",
        ]
        entry = db.scalar(select(AuditLog).where(AuditLog.action == "allergy.delete"))
        assert entry.detail["allergen"] == "SULFONAMIDE"
        assert entry.detail["allergen_name"] == "Sulfonamides"
        assert entry.patient_id == stored_patient(client, number).id
        assert db.scalar(select(func.count()).select_from(Allergy)) == 1
        assert db.get(Allergy, first["id"]) is not None


def test_allergy_validation_and_custom_allergen(client):
    patient = create_patient(client, name="Allergy Validation")
    number = patient["patient_no"]

    bad_severity = client.post(
        f"/api/patients/{number}/allergies",
        json={
            "allergen": "PENICILLIN",
            "allergy_type": "drug",
            "severity": "extreme",
            "recorded_at": "2026-08-01",
        },
    )
    assert bad_severity.status_code == 422
    assert "severity" in bad_severity.json()["message"]

    custom = add_allergy(
        client, number, allergen="LATEX", allergy_type="other", severity="moderate"
    )
    assert custom["allergen"] == "LATEX"
    assert client.get(f"/api/patients/{number}/allergies").json()["data"][0]["allergen"] == "LATEX"
    assert client.get("/api/patients/P20269999/allergies").status_code == 404


def test_soft_deleted_patient_keeps_allergies_and_audit(client):
    patient = create_patient(client, name="Soft Deleted")
    number = patient["patient_no"]
    add_allergy(client, number, allergen="CEPHALOSPORIN", severity="moderate")
    client.delete(f"/api/patients/{number}")
    with client.app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Allergy)) == 1
        # The shared reader hides a soft-deleted patient's list from callers.
        assert get_patient_allergens(db, number) == []


def test_allergen_codes_are_normalised_for_the_validation_engine(client):
    patient = create_patient(client, name="Case Normalise")
    number = patient["patient_no"]
    created = add_allergy(client, number, allergen=" penicillin ", severity="severe")
    assert created["allergen"] == "PENICILLIN"

    updated = client.patch(f"/api/allergies/{created['id']}", json={"severity": "mild"})
    assert updated.status_code == 200
    assert updated.json()["data"]["allergen"] == "PENICILLIN"
    assert updated.json()["data"]["severity"] == "mild"

    detail = client.get(f"/api/patients/{number}").json()["data"]
    assert [item["allergen"] for item in detail["allergies"]] == ["PENICILLIN"]


def test_allergy_route_validation_and_missing_records(client):
    patient = create_patient(client, name="Route Checks")
    number = patient["patient_no"]

    blank = client.post(
        f"/api/patients/{number}/allergies",
        json={
            "allergen": "   ",
            "allergy_type": "drug",
            "severity": "mild",
            "recorded_at": "2026-08-01",
        },
    )
    assert blank.status_code == 422
    assert "allergen" in blank.json()["message"]

    bad_type = client.post(
        f"/api/patients/{number}/allergies",
        json={
            "allergen": "ASPIRIN",
            "allergy_type": "vaccine",
            "severity": "mild",
            "recorded_at": "2026-08-01",
        },
    )
    assert bad_type.status_code == 422
    assert "allergy_type" in bad_type.json()["message"]

    incomplete = client.post(f"/api/patients/{number}/allergies", json={"allergen": "ASPIRIN"})
    assert incomplete.status_code == 422
    assert "severity" in incomplete.json()["message"]

    assert client.patch("/api/allergies/9999", json={"severity": "mild"}).status_code == 404
    assert client.delete("/api/allergies/9999").status_code == 404
    assert client.get("/api/patients").json()["data"]["total"] == 1

    # A soft-deleted patient hides the whole allergy surface.
    client.delete(f"/api/patients/{number}")
    assert client.get(f"/api/patients/{number}/allergies").status_code == 404
    created = client.post(
        f"/api/patients/{number}/allergies",
        json={
            "allergen": "ASPIRIN",
            "allergy_type": "drug",
            "severity": "mild",
            "recorded_at": "2026-08-01",
        },
    )
    assert created.status_code == 404


def test_allergy_audit_entries_carry_the_allergen(client):
    patient = create_patient(client, name="Audit Detail")
    number = patient["patient_no"]
    created = add_allergy(client, number, allergen="CEPHALOSPORIN", severity="severe")
    client.patch(f"/api/allergies/{created['id']}", json={"severity": "moderate"})

    with client.app.state.sessions() as db:
        create_entry = db.scalar(select(AuditLog).where(AuditLog.action == "allergy.create"))
        assert create_entry.detail == {
            "id": created["id"],
            "allergen": "CEPHALOSPORIN",
            "allergen_name": "Cephalosporins",
            "severity": "severe",
        }
        update_entry = db.scalar(select(AuditLog).where(AuditLog.action == "allergy.update"))
        assert update_entry.detail["allergen"] == "CEPHALOSPORIN"
        assert update_entry.detail["allergen_name"] == "Cephalosporins"
        assert update_entry.detail["severity"] == "moderate"
        assert create_entry.patient_id == update_entry.patient_id
