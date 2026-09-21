"""M2-06 acceptance: the medical-history timeline.

`test_auth_grants.py` builds the accounts this file needs: user 1 is the admin in
Information Technology, user 3 is a junior in Cardiology, user 4 a senior there.
A history entry is a patient child row, so the questions are the ones every child
row answers the same way -- does another department see it (no, a 404), does a
soft-deleted patient take it along (yes), and does the write leave a trail (yes).

The ordering assertions are the part specific to this table: `onset_date` is
optional, and the timeline has to read newest-first with the undated entries at
the bottom on every dialect the schema targets, not just on SQLite.
"""

from sqlalchemy import select
from test_auth_grants import client as auth_client
from test_auth_grants import headers

from app.models import AuditLog, Patient, PatientHistory

client = auth_client

IT = 1
CARDIOLOGY = 3


def create_patient(client, user=IT, **overrides):
    body = {"name": "History Subject", "gender": "unknown", "department": "Information Technology"}
    body.update(overrides)
    response = client.post("/api/patients", headers=headers(client, user), json=body)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def add_history(client, user, patient_no, **overrides):
    body = {"diagnosis": "Type 2 diabetes", "onset_date": "2019-05-01"}
    body.update(overrides)
    return client.post(
        f"/api/patients/{patient_no}/histories", headers=headers(client, user), json=body
    )


def create_history(client, user, patient_no, **overrides):
    response = add_history(client, user, patient_no, **overrides)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def list_history(client, user, patient_no):
    response = client.get(f"/api/patients/{patient_no}/histories", headers=headers(client, user))
    assert response.status_code == 200, response.text
    return response.json()["data"]


def patient_id(client, patient_no):
    """The row id, which the patient payload does not carry.

    `PatientSummary` publishes the number and not the primary key, so the two
    assertions that need to join back to the table resolve it here.
    """
    with client.app.state.sessions() as db:
        return db.scalar(select(Patient.id).where(Patient.patient_no == patient_no))


def test_the_lifecycle_creates_reads_edits_and_deletes(client):
    patient = create_patient(client)
    created = create_history(client, IT, patient["patient_no"], diagnosis="Hypertension")

    assert created["diagnosis"] == "Hypertension"
    assert created["onset_date"] == "2019-05-01"
    assert created["notes"] == ""
    assert created["id"] == list_history(client, IT, patient["patient_no"])[0]["id"]

    edited = client.patch(
        f"/api/histories/{created['id']}",
        headers=headers(client, IT),
        json={"diagnosis": "Hypertension", "notes": "Controlled by diet"},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["data"]["notes"] == "Controlled by diet"

    removed = client.delete(f"/api/histories/{created['id']}", headers=headers(client, IT))
    assert removed.status_code == 200, removed.text
    assert removed.json()["data"] == {}
    assert list_history(client, IT, patient["patient_no"]) == []


def test_the_timeline_reads_newest_onset_first_and_puts_undated_entries_last(client):
    patient = create_patient(client)
    for diagnosis, onset in (
        ("Oldest", "2015-01-01"),
        ("Newest", "2024-12-31"),
        ("Undated", None),
    ):
        # `onset_date` is sent explicitly, including as null: leaving the key out
        # of this call would fall back to the helper's default date, and the row
        # that has to sort last would arrive with 2019 spelled on it instead.
        create_history(client, IT, patient["patient_no"], diagnosis=diagnosis, onset_date=onset)

    # "Undated" is last because SQLite and MySQL both sort NULL lowest and the
    # reader makes that explicit; ordering by the string alone would pass on one
    # dialect and quietly differ on the other.
    assert [row["diagnosis"] for row in list_history(client, IT, patient["patient_no"])] == [
        "Newest",
        "Oldest",
        "Undated",
    ]


def test_an_undated_entry_is_kept_rather_than_refused(client):
    """The contract requires only `diagnosis`, so a missing date is not a 422."""
    patient = create_patient(client)
    created = create_history(
        client, IT, patient["patient_no"], diagnosis="Childhood asthma", onset_date=None
    )

    assert created["onset_date"] is None
    assert created["diagnosis"] == "Childhood asthma"


def test_a_partial_edit_changes_only_what_it_names(client):
    patient = create_patient(client)
    created = create_history(
        client, IT, patient["patient_no"], diagnosis="Asthma", notes="Wheeze at night"
    )

    # Only the date is sent. Reusing the create body here would have made this
    # call impossible to express without restating the diagnosis.
    edited = client.patch(
        f"/api/histories/{created['id']}",
        headers=headers(client, IT),
        json={"onset_date": "2011-03-04"},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["data"]["diagnosis"] == "Asthma"
    assert edited.json()["data"]["notes"] == "Wheeze at night"
    assert edited.json()["data"]["onset_date"] == "2011-03-04"


def test_a_null_date_clears_it_and_a_null_diagnosis_is_refused(client):
    patient = create_patient(client)
    created = create_history(client, IT, patient["patient_no"])

    cleared = client.patch(
        f"/api/histories/{created['id']}",
        headers=headers(client, IT),
        json={"onset_date": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["data"]["onset_date"] is None

    # `diagnosis` is the column NOT NULL forbids it; `notes` refuses it by choice,
    # so that clearing free text is spelled `""` and not two different ways.
    for field in ("diagnosis", "notes"):
        refused = client.patch(
            f"/api/histories/{created['id']}", headers=headers(client, IT), json={field: None}
        )
        assert refused.status_code == 422, (field, refused.text)


def test_another_departments_patient_is_a_404_on_every_verb(client):
    """Not a 403: the caller is not told that the patient exists at all."""
    patient = create_patient(client)
    created = create_history(client, IT, patient["patient_no"])

    assert add_history(client, CARDIOLOGY, patient["patient_no"]).status_code == 404
    assert (
        client.get(
            f"/api/patients/{patient['patient_no']}/histories", headers=headers(client, CARDIOLOGY)
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/histories/{created['id']}",
            headers=headers(client, CARDIOLOGY),
            json={"diagnosis": "Hijacked"},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/histories/{created['id']}", headers=headers(client, CARDIOLOGY)
        ).status_code
        == 404
    )
    assert list_history(client, IT, patient["patient_no"])[0]["diagnosis"] == "Type 2 diabetes"


def test_a_soft_deleted_patient_takes_their_history_with_them(client):
    patient = create_patient(client)
    created = create_history(client, IT, patient["patient_no"])

    assert (
        client.delete(
            f"/api/patients/{patient['patient_no']}", headers=headers(client, IT)
        ).status_code
        == 200
    )

    assert (
        client.get(
            f"/api/patients/{patient['patient_no']}/histories", headers=headers(client, IT)
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/histories/{created['id']}", headers=headers(client, IT), json={"notes": "x"}
        ).status_code
        == 404
    )
    # The row stays in place and is filtered out with the parent, per the contract.
    with client.app.state.sessions() as db:
        assert db.get(PatientHistory, created["id"]) is not None


def test_an_unknown_entry_is_a_404_on_every_verb(client):
    assert (
        client.patch(
            "/api/histories/9999", headers=headers(client, IT), json={"notes": "x"}
        ).status_code
        == 404
    )
    assert client.delete("/api/histories/9999", headers=headers(client, IT)).status_code == 404


def test_every_history_route_refuses_an_anonymous_caller(client):
    """A history is clinical data: the default-protection rule covers the new paths."""
    for method, path in (
        ("get", "/api/patients/P20260001/histories"),
        ("post", "/api/patients/P20260001/histories"),
        ("patch", "/api/histories/1"),
        ("delete", "/api/histories/1"),
    ):
        response = client.request(
            method.upper(),
            path,
            json={"diagnosis": "Anonymous", "onset_date": None},
        )
        assert response.status_code == 401, (method, path)


def test_every_history_write_lands_in_the_audit_trail(client):
    patient = create_patient(client)
    created = create_history(client, IT, patient["patient_no"], diagnosis="Migraine")
    client.patch(
        f"/api/histories/{created['id']}",
        headers=headers(client, IT),
        json={"diagnosis": "Migraine with aura"},
    )
    client.delete(f"/api/histories/{created['id']}", headers=headers(client, IT))

    rows = client.get(
        "/api/audit-logs",
        params={"object_type": "history", "size": 50},
        headers=headers(client, IT),
    ).json()["data"]["items"]
    by_action = {row["action"]: row for row in rows}
    assert set(by_action) == {"history.create", "history.update", "history.delete"}

    # The deleted entry's identity is read back out of the trail, which is the
    # point of writing the snapshot before the row goes.
    assert by_action["history.delete"]["detail"]["diagnosis"] == "Migraine with aura"
    assert by_action["history.delete"]["detail"]["onset_date"] == "2019-05-01"
    # `app.audit` retains no bodies, and `notes` is one.
    assert "notes" not in by_action["history.update"]["detail"]

    # The response schema does not publish `patient_id`, so the clinical part of
    # the attribution -- that this write belongs to one chart, and which -- is
    # read off the table. Without `patient_id=` at the call site every row here
    # would read as hospital-wide activity that no chart could be audited from.
    pid = patient_id(client, patient["patient_no"])
    with client.app.state.sessions() as db:
        assert {row.patient_id for row in db.scalars(select(AuditLog))} == {pid}


def test_the_patient_detail_embeds_the_same_timeline(client):
    patient = create_patient(client)
    create_history(client, IT, patient["patient_no"], diagnosis="Older", onset_date="2016-02-02")
    create_history(client, IT, patient["patient_no"], diagnosis="Newer", onset_date="2023-08-09")

    detail = client.get(
        f"/api/patients/{patient['patient_no']}", headers=headers(client, IT)
    ).json()["data"]

    # Required by the contract and empty until this table existed.
    assert [row["diagnosis"] for row in detail["histories"]] == ["Newer", "Older"]
    assert set(detail["histories"][0]) == {
        "id",
        "diagnosis",
        "onset_date",
        "notes",
        "created_at",
    }
    # One reader for both, so the embedded list cannot disagree with the endpoint.
    assert detail["histories"] == list_history(client, IT, patient["patient_no"])


def test_a_new_patient_starts_with_an_empty_timeline(client):
    patient = create_patient(client)
    assert list_history(client, IT, patient["patient_no"]) == []


def test_the_history_rows_survive_a_restart(client):
    """A row written through the API is a row, not a request-scoped object."""
    patient = create_patient(client)
    created = create_history(client, IT, patient["patient_no"])

    with client.app.state.sessions() as db:
        stored = db.scalar(select(PatientHistory).where(PatientHistory.id == created["id"]))
        assert stored is not None
        assert stored.patient_id == patient_id(client, patient["patient_no"])
        assert stored.diagnosis == created["diagnosis"]
        # The column default is applied by SQLite as well as by the ORM, so a row
        # inserted without notes carries "" and not NULL.
        assert stored.notes == ""
