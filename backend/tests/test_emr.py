"""M4 acceptance scenarios, six-cell matrix and security boundaries."""

from copy import deepcopy

import pytest
from sqlalchemy import select
from sqlalchemy.orm.exc import StaleDataError
from test_meetings import client as meeting_client
from test_meetings import create_patient, headers

from app.emr_models import Drug, EmrRecord
from app.models import AuditLog

client = meeting_client

CONTENT = {
    "chief_complaint": "Breathlessness",
    "diagnosis": "Heart failure",
    "note_date": "2026-09-19",
    "severity": "moderate",
}


def call(client, method, path, body=None, actor=3, code=200):
    response = client.request(
        method,
        "/api" + path,
        headers=headers(client, actor),
        **({"json": body} if body is not None else {}),
    )
    assert response.status_code == code, response.text
    return response.json()["data"]


def new_record(client, allergic=False):
    patient = create_patient(client)
    if allergic:
        for code in ("PENICILLIN", "SULFONAMIDE"):
            call(
                client,
                "POST",
                f"/patients/{patient}/allergies",
                {
                    "allergen": code,
                    "allergy_type": "drug",
                    "severity": "severe",
                    "recorded_at": "2026-09-01",
                },
            )
    template = call(client, "GET", "/emr/templates")[0]
    return call(
        client, "POST", "/emr/records", {"patient_no": patient, "template_id": template["id"]}
    )


def save(client, row, content=None, code=200):
    return call(
        client,
        "PATCH",
        f"/emr/records/{row['id']}",
        {
            "version": row["version"],
            "revision": row["revision"],
            "content_json": CONTENT if content is None else content,
        },
        code=code,
    )


def drug(code="FURO20", dose="20mg", frequency="qd"):
    return {"order_type": "drug", "drug_code": code, "dose": dose, "frequency": frequency}


def test_order_edits_preserve_drug_name_after_reload(client):
    record = new_record(client)
    order = call(client, "POST", "/emr/orders", {"record_id": record["id"], "items": [drug()]})[0]
    assert order["content_json"]["drug_name"] == "Furosemide tablets"
    for item, name in (
        (drug(dose="40mg"), "Furosemide tablets"),
        (drug("AMOX500", "0.5g", "tid"), "Amoxicillin capsules"),
    ):
        changed = call(client, "PATCH", f"/emr/orders/{order['id']}", item)
        assert changed["content_json"]["drug_name"] == name
        stored = call(client, "GET", f"/emr/orders?record_id={record['id']}")[0]
        assert stored["content_json"]["drug_name"] == name
        for key in ("drug_code", "dose", "frequency"):
            assert stored["content_json"][key] == item[key]


def test_templates_snapshot_validation_and_permissions(client):
    templates = call(client, "GET", "/emr/templates")
    assert len(templates) == 2
    assert all(len(t["fields_json"]["fields"]) >= 6 for t in templates)
    body = {k: v for k, v in templates[0].items() if k != "id"}
    call(client, "POST", "/emr/templates", body, code=403)
    broken = deepcopy(body)
    broken["fields_json"]["fields"][0]["type"] = "checkbox"
    call(client, "POST", "/emr/templates", broken, actor=1, code=422)
    row = new_record(client)
    body["is_active"] = False
    body["fields_json"]["fields"][0]["label"] = "Changed label"
    call(client, "PATCH", f"/emr/templates/{row['template_id']}", body, actor=1)
    assert (
        call(client, "GET", f"/emr/records/{row['id']}")["template_snapshot"]["fields_json"][
            "fields"
        ][0]["label"]
        == "Chief complaint"
    )
    call(
        client,
        "POST",
        "/emr/records",
        {"patient_no": row["patient_no"], "template_id": row["template_id"]},
        code=422,
    )
    save(client, row, {"diagnosis": "Only diagnosis"}, code=422)
    for extra in (
        {"temperature": "warm"},
        {"note_date": "tomorrow"},
        {"severity": "invalid"},
        {"unknown": 1},
    ):
        save(client, row, {**CONTENT, **extra}, code=422)


def test_versions_rejection_archive_amendment_and_lock(client):
    row = new_record(client)
    path = f"/emr/records/{row['id']}"
    call(client, "POST", path + "/submit", code=422)
    saved = save(client, row)
    assert saved["version"] == 1 and saved["revision"] > row["revision"]
    save(client, row, code=409)
    row = call(client, "POST", path + "/submit")
    assert row["version"] == 2 and row["status"] == "pending"
    save(client, row, code=409)
    call(client, "GET", "/emr/reviews", code=403)
    call(client, "GET", "/emr/reviews", actor=1, code=403)
    assert call(client, "GET", "/emr/reviews", actor=2)["total"] == 1
    call(client, "POST", path + "/review", {"action": "reject"}, actor=2, code=422)
    row = call(
        client,
        "POST",
        path + "/review",
        {"action": "reject", "comment": "Explain symptoms"},
        actor=2,
    )
    assert (
        call(client, "GET", "/emr/my-submissions")["items"][0]["review_comment"]
        == "Explain symptoms"
    )
    updated = {**CONTENT, "history": "Revised history"}
    save(client, row, updated)
    row = call(client, "POST", path + "/submit")
    assert row["version"] == 3
    row = call(client, "POST", path + "/review", {"action": "approve"}, actor=2)
    assert row["status"] == "archived" and row["reviewer_id"] == 2 and row["reviewed_at"]
    save(client, row, code=409)
    for suffix in ("/submit", "/archive"):
        call(client, "POST", path + suffix, actor=2 if suffix == "/archive" else 3, code=409)
    call(client, "POST", "/emr/orders", {"record_id": row["id"], "items": [drug()]}, code=409)
    history = call(client, "GET", path + "/versions")
    assert [v["version"] for v in history] == [1, 2, 3]
    assert history[0]["content_json"] == CONTENT == history[1]["content_json"]
    assert history[2]["content_json"] == updated
    call(client, "POST", path + "/amend", {"content_json": {"plan": "Addendum"}}, actor=2, code=403)
    amended = call(client, "POST", path + "/amend", {"content_json": {"plan": "Addendum"}})
    assert amended["version"] == 4 and amended["content_json"] == updated
    history2 = call(client, "GET", path + "/versions")
    assert history2[:3] == history and history2[3]["content_json"]["plan"] == "Addendum"


@pytest.mark.parametrize(
    "allergic,item,expected,kinds",
    [
        (True, drug("AMOX500", "0.5g", "tid"), "blocked", ["allergy"]),
        (True, drug("SMZ", "2 tablets", "bid"), "blocked", ["allergy"]),
        (True, drug(dose="80mg"), "warning", ["dose"]),
        (True, drug(), "passed", []),
        (True, drug("AMOX500", "2g", "tid"), "blocked", ["allergy", "dose"]),
        (False, drug("AMOX500", "0.5g", "tid"), "passed", []),
    ],
)
def test_six_cell_matrix_and_server_bypass(client, allergic, item, expected, kinds):
    row = new_record(client, allergic)
    code = 409 if expected == "blocked" else 200
    result = call(
        client,
        "POST",
        "/emr/orders/validate",
        {"patient_no": row["patient_no"], "items": [item]},
    )
    assert result["overall"] == expected
    assert [r["kind"] for r in result["results"][0]["reasons"]] == kinds
    call(
        client,
        "POST",
        "/emr/orders",
        {"record_id": row["id"], "items": [item], "override_reason": "Clinical decision"},
        code=code,
    )
    stored = call(client, "GET", f"/emr/orders?record_id={row['id']}")
    assert len(stored) == (0 if expected == "blocked" else 1)
    if expected == "blocked":
        response = client.post(
            "/api/emr/orders",
            headers=headers(client),
            json={"record_id": row["id"], "items": [item]},
        )
        assert any(name in response.json()["message"] for name in ("Penicillins", "Sulfonamides"))
    if stored:
        assert stored[0]["validation_status"] == expected
        assert stored[0]["override_reason"] == "Clinical decision"
    else:
        with client.app.state.sessions() as db:
            assert db.scalar(select(AuditLog).where(AuditLog.action == "medical_order.blocked"))


def test_order_modify_stop_audit_invalid_and_archive(client):
    row = new_record(client, True)
    order = call(client, "POST", "/emr/orders", {"record_id": row["id"], "items": [drug()]})[0]
    path = f"/emr/orders/{order['id']}"
    changed = call(client, "PATCH", path, drug(dose="40mg"))
    assert changed["content_json"]["dose"] == "40mg" and changed["validation_status"] == "passed"
    call(client, "PATCH", path, drug("AMOX500", "0.5g", "tid"), code=409)
    assert (
        call(client, "GET", f"/emr/orders?record_id={row['id']}")[0]["content_json"]["dose"]
        == "40mg"
    )
    assert call(client, "POST", path + "/stop")["status"] == "stopped"
    call(client, "POST", path + "/stop", code=409)
    call(client, "PATCH", path, drug(), code=409)
    call(client, "POST", "/emr/orders", {"record_id": 99999, "items": [drug()]}, code=404)
    missing = client.post(
        "/api/emr/orders",
        headers=headers(client),
        json={"record_id": row["id"], "items": [{"order_type": "drug", "drug_code": "FURO20"}]},
    )
    assert missing.status_code == 422 and "dose" in missing.json()["message"]
    call(client, "POST", "/emr/orders", {"record_id": row["id"], "items": [{"order_type": "lab"}]})
    current = call(client, "GET", f"/emr/records/{row['id']}")
    save(client, current)
    call(client, "POST", f"/emr/records/{row['id']}/submit")
    call(client, "POST", f"/emr/records/{row['id']}/archive", actor=2)
    call(client, "POST", path + "/stop", code=409)
    call(client, "PATCH", path, drug(), code=409)
    with client.app.state.sessions() as db:
        actions = set(db.scalars(select(AuditLog.action)))
        assert {
            "medical_order.create",
            "medical_order.modify",
            "medical_order.stop",
            "medical_order.blocked",
            "emr_record.view",
        } <= actions


def test_scope_filters_ownership_and_atomic_batch(client):
    row = new_record(client, True)
    path = f"/emr/records/{row['id']}"
    assert call(client, "GET", "/emr/records", actor=4)["total"] == 0
    assert call(client, "GET", "/emr/records", actor=1)["total"] == 1
    for suffix in ("", "/versions"):
        call(client, "GET", path + suffix, actor=4, code=404)
    call(client, "GET", f"/emr/orders?record_id={row['id']}", actor=4, code=404)
    call(
        client,
        "POST",
        "/emr/orders/validate",
        {"patient_no": row["patient_no"], "items": [drug()]},
        actor=4,
        code=404,
    )
    call(client, "POST", path + "/submit", actor=2, code=403)
    assert call(client, "GET", "/emr/my-submissions", actor=2)["total"] == 0
    assert (
        call(
            client,
            "GET",
            f"/emr/records?patient_no={row['patient_no']}&author_id=3&status=draft&size=1",
        )["total"]
        == 1
    )
    assert call(client, "GET", "/emr/records?status=archived")["total"] == 0
    call(
        client,
        "POST",
        "/emr/orders",
        {"record_id": row["id"], "items": [drug(), drug("AMOX500", "0.5g", "tid")]},
        code=409,
    )
    assert call(client, "GET", f"/emr/orders?record_id={row['id']}") == []
    for path in ("/emr/records/9999", "/emr/templates/9999"):
        call(client, "GET", path, code=404)
    call(client, "POST", "/emr/orders/9999/stop", code=404)


@pytest.mark.parametrize(
    "item",
    [
        drug(dose="NaN"),
        drug(dose="-1mg"),
        drug(dose="1 tablets"),
        drug(frequency="unknown"),
        drug(code="UNKNOWN"),
    ],
)
def test_invalid_doses_and_drugs(client, item):
    row = new_record(client)
    call(client, "POST", "/emr/orders", {"record_id": row["id"], "items": [item]}, code=422)


def test_configurable_rules_units_and_daily_frequency(client):
    assert call(client, "GET", "/drugs?q=FURO20")[0]["code"] == "FURO20"
    assert call(client, "GET", "/drugs?q=amoxicillin")[0]["code"] == "AMOX500"
    assert call(client, "GET", "/drugs?q=missing") == []
    row = new_record(client)
    for item, status in [
        (drug(dose="0.02g"), "passed"),
        (drug(dose="20mg", frequency="tid"), "warning"),
    ]:
        result = call(
            client,
            "POST",
            "/emr/orders/validate",
            {"patient_no": row["patient_no"], "items": [item]},
        )
        assert result["overall"] == status
    with client.app.state.sessions() as db:
        d = db.get(Drug, "FURO20")
        d.dose_rule = {**d.dose_rule, "max": 100}
        db.commit()
    assert (
        call(
            client,
            "POST",
            "/emr/orders/validate",
            {"patient_no": row["patient_no"], "items": [drug(dose="80mg")]},
        )["overall"]
        == "passed"
    )


def test_database_compare_and_swap(client):
    row = new_record(client)
    with client.app.state.sessions() as first, client.app.state.sessions() as second:
        a, b = first.get(EmrRecord, row["id"]), second.get(EmrRecord, row["id"])
        a.content_json = CONTENT
        first.commit()
        b.content_json = {**CONTENT, "plan": "stale"}
        with pytest.raises(StaleDataError):
            second.commit()
