"""T17 acceptance: patient groups inside the T09 department scope.

`test_auth_grants.py` builds the accounts this file needs: user 1 is the admin in
Information Technology, user 3 is a junior in Cardiology, user 4 a senior there.
A group is the one place where a caller names a patient who is not already in
front of them, so most of what follows is about what a group may *not* do: show
another department's group, take a patient from another department, or widen the
scope of the patient list.
"""

from sqlalchemy import select
from test_auth_grants import client as auth_client
from test_auth_grants import headers

from app.models import AuditLog, Patient, PatientGroup, PatientGroupMember

client = auth_client

IT = 1
CARDIOLOGY = 3


def create_patient(client, user=IT, **overrides):
    body = {"name": "Group Subject", "gender": "unknown", "department": "Information Technology"}
    body.update(overrides)
    response = client.post("/api/patients", headers=headers(client, user), json=body)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def create_group(client, user=IT, **overrides):
    body = {"name": "Chronic follow-up"}
    body.update(overrides)
    response = client.post("/api/patient-groups", headers=headers(client, user), json=body)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def add_members(client, user, group_id, patient_nos):
    return client.post(
        f"/api/patient-groups/{group_id}/members",
        headers=headers(client, user),
        json={"patient_nos": patient_nos},
    )


def remove_members(client, user, group_id, patient_nos):
    # `TestClient.delete` takes no body, and this route reads its patients from one.
    return client.request(
        "DELETE",
        f"/api/patient-groups/{group_id}/members",
        headers=headers(client, user),
        json={"patient_nos": patient_nos},
    )


def group_names(client, user):
    body = client.get("/api/patient-groups", headers=headers(client, user)).json()["data"]
    return [row["name"] for row in body]


def test_a_group_belongs_to_the_department_that_created_it(client):
    technology = create_group(client)
    create_group(client, user=CARDIOLOGY, name="Cardiology follow-up")

    # Scenario S2: the junior in Cardiology sees their own group and not the other
    # department's -- the scope filters the list rather than flagging the payload.
    assert group_names(client, CARDIOLOGY) == ["Cardiology follow-up"]
    # The admin carries `data.all`, so their list is the whole hospital.
    assert group_names(client, 1) == ["Cardiology follow-up", "Chronic follow-up"]

    # And the group outside the scope is a 404 on every verb that names it, not a
    # 403: the caller is not told that the group exists at all.
    path = f"/api/patient-groups/{technology['id']}"
    assert client.get("/api/patient-groups", headers=headers(client, CARDIOLOGY)).status_code == 200
    assert (
        client.patch(
            path, headers=headers(client, CARDIOLOGY), json={"name": "Hijacked"}
        ).status_code
        == 404
    )
    assert client.delete(path, headers=headers(client, CARDIOLOGY)).status_code == 404
    assert add_members(client, CARDIOLOGY, technology["id"], ["P20260001"]).status_code == 404
    assert group_names(client, 1) == ["Cardiology follow-up", "Chronic follow-up"]


def test_naming_another_department_needs_data_all(client):
    """The department rule is the same one patient creation uses, through `patients.py`."""
    refused = client.post(
        "/api/patient-groups",
        headers=headers(client, CARDIOLOGY),
        json={"name": "Reaching over", "department": "Information Technology"},
    )
    assert refused.status_code == 403
    assert "another department" in refused.json()["message"]

    unknown = client.post(
        "/api/patient-groups",
        headers=headers(client, CARDIOLOGY),
        json={"name": "Reaching over", "department": "Nowhere"},
    )
    assert unknown.status_code == 404

    # Leaving the department out is how the screen creates a group: it lands in the
    # caller's own department.
    create_group(client, user=CARDIOLOGY, name="Own department")
    assert group_names(client, CARDIOLOGY) == ["Own department"]


def test_group_names_are_unique_inside_a_department_only(client):
    technology = create_group(client)
    clash = client.post(
        "/api/patient-groups",
        headers=headers(client, IT),
        json={"name": technology["name"]},
    )
    assert clash.status_code == 409
    assert technology["name"] in clash.json()["message"]

    # The same name in another department is a different group, not a conflict.
    create_group(client, user=CARDIOLOGY, name=technology["name"])
    assert group_names(client, CARDIOLOGY) == [technology["name"]]

    other = create_group(client, name="Second IT group")
    assert (
        client.patch(
            f"/api/patient-groups/{other['id']}",
            headers=headers(client, IT),
            json={"name": technology["name"]},
        ).status_code
        == 409
    )
    # Renaming a group to the name it already has is not a conflict with itself.
    same = client.patch(
        f"/api/patient-groups/{other['id']}",
        headers=headers(client, IT),
        json={"name": other["name"], "description": "Monthly review"},
    )
    assert same.status_code == 200
    assert same.json()["data"]["description"] == "Monthly review"
    assert (
        client.patch(
            f"/api/patient-groups/{other['id']}",
            headers=headers(client, IT),
            json={"name": None},
        ).status_code
        == 422
    )


def test_members_are_added_counted_and_removed(client):
    group = create_group(client)
    first = create_patient(client, name="First")
    second = create_patient(client, name="Second")

    added = add_members(client, IT, group["id"], [first["patient_no"], second["patient_no"]])
    assert added.status_code == 200
    assert added.json()["data"]["member_count"] == 2

    # Scenario S1: the same patient twice is a 409 that names them, rather than a
    # second row that would make the count lie.
    duplicate = add_members(client, IT, group["id"], [first["patient_no"]])
    assert duplicate.status_code == 409
    assert first["patient_no"] in duplicate.json()["message"]

    missing = add_members(client, IT, group["id"], ["P20269999"])
    assert missing.status_code == 404
    assert "P20269999" in missing.json()["message"]

    removed = remove_members(client, IT, group["id"], [first["patient_no"]])
    assert removed.status_code == 200
    assert removed.json()["data"]["member_count"] == 1

    absent = remove_members(client, IT, group["id"], [first["patient_no"]])
    assert absent.status_code == 404
    assert first["patient_no"] in absent.json()["message"]

    assert add_members(client, IT, group["id"], []).status_code == 422


def test_a_soft_deleted_member_stops_being_counted(client):
    """The count has to agree with the list the same group filters, which hides them."""
    group = create_group(client)
    patient = create_patient(client, name="Leaver")
    add_members(client, IT, group["id"], [patient["patient_no"]])
    deleted = client.delete(f"/api/patients/{patient['patient_no']}", headers=headers(client, IT))
    assert deleted.status_code == 200

    listed = client.get("/api/patient-groups", headers=headers(client, IT)).json()["data"]
    assert [row["member_count"] for row in listed] == [0]
    filtered = client.get(
        "/api/patients", params={"group_id": group["id"]}, headers=headers(client, IT)
    ).json()["data"]
    assert filtered["total"] == 0


def test_a_patient_from_another_department_cannot_be_a_member(client):
    """Otherwise an admin could park a Cardiology patient in an IT group."""
    group = create_group(client)
    outsider = create_patient(client, name="Cardiology Patient", department="Cardiology")

    refused = add_members(client, IT, group["id"], [outsider["patient_no"]])
    assert refused.status_code == 422
    assert outsider["patient_no"] in refused.json()["message"]
    with client.app.state.sessions() as db:
        assert db.scalar(select(PatientGroupMember)) is None


def test_the_group_filter_narrows_the_list_and_never_widens_it(client):
    group = create_group(client)
    inside = create_patient(client, name="Inside")
    create_patient(client, name="Outside")
    add_members(client, IT, group["id"], [inside["patient_no"]])

    filtered = client.get(
        "/api/patients", params={"group_id": group["id"]}, headers=headers(client, IT)
    ).json()["data"]
    assert filtered["total"] == 1
    assert filtered["items"][0]["patient_no"] == inside["patient_no"]

    # Scenario S1: the filter stacks with the name search rather than replacing it.
    stacked = client.get(
        "/api/patients",
        params={"group_id": group["id"], "name": "Outside"},
        headers=headers(client, IT),
    ).json()["data"]
    assert stacked["total"] == 0

    # A caller from another department filtering by this group gets an empty page,
    # not a 404 and not a row: the T09 scope is applied before the filter.
    foreign = client.get(
        "/api/patients", params={"group_id": group["id"]}, headers=headers(client, CARDIOLOGY)
    )
    assert foreign.status_code == 200
    assert foreign.json()["data"]["total"] == 0

    unknown = client.get("/api/patients", params={"group_id": 9999}, headers=headers(client, IT))
    assert unknown.status_code == 200
    assert unknown.json()["data"]["total"] == 0


def test_deleting_a_group_keeps_the_patients_and_drops_the_membership(client):
    group = create_group(client)
    patient = create_patient(client, name="Keeper")
    add_members(client, IT, group["id"], [patient["patient_no"]])

    detail = client.get(f"/api/patients/{patient['patient_no']}", headers=headers(client, IT))
    assert detail.json()["data"]["groups"] == [{**group, "member_count": 1}]

    deleted = client.delete(f"/api/patient-groups/{group['id']}", headers=headers(client, IT))
    assert deleted.status_code == 200
    assert deleted.json()["data"]["member_count"] == 1

    # Scenario S2: the people stay in the directory, the grouping goes.
    after = client.get(f"/api/patients/{patient['patient_no']}", headers=headers(client, IT))
    assert after.status_code == 200
    assert after.json()["data"]["groups"] == []
    assert group_names(client, IT) == []
    with client.app.state.sessions() as db:
        assert db.scalar(select(PatientGroupMember)) is None
        assert db.scalar(select(PatientGroup).where(PatientGroup.id == group["id"])) is None
        kept = db.scalar(select(Patient).where(Patient.patient_no == patient["patient_no"]))
        assert kept is not None


def test_every_group_write_lands_in_the_audit_trail(client):
    group = create_group(client)
    patient = create_patient(client, name="Audited")
    staying = create_patient(client, name="Staying")
    add_members(client, IT, group["id"], [patient["patient_no"], staying["patient_no"]])
    client.patch(
        f"/api/patient-groups/{group['id']}",
        headers=headers(client, IT),
        json={"description": "Monthly review"},
    )
    remove_members(client, IT, group["id"], [patient["patient_no"]])
    client.delete(f"/api/patient-groups/{group['id']}", headers=headers(client, IT))

    rows = client.get(
        "/api/audit-logs",
        params={"object_type": "patient_group", "size": 50},
        headers=headers(client, 1),
    ).json()["data"]["items"]
    by_action = {row["action"]: row for row in rows}
    assert set(by_action) == {
        "patient_group.create",
        "patient_group.members.add",
        "patient_group.update",
        "patient_group.members.remove",
        "patient_group.delete",
    }
    added = by_action["patient_group.members.add"]["detail"]
    assert added["patient_nos"] == [patient["patient_no"], staying["patient_no"]]
    removed = by_action["patient_group.members.remove"]["detail"]
    assert removed["patient_nos"] == [patient["patient_no"]]
    # The delete row says how much membership it dropped: one of the two was
    # removed first, and the patients themselves are not part of that count.
    assert by_action["patient_group.delete"]["detail"]["patients_kept"] == 1
    with client.app.state.sessions() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == "patient_group.delete"))


def test_every_group_route_refuses_an_anonymous_caller(client):
    """Groups are clinical data: the default-protection rule covers the new paths."""
    for method, path in (
        ("get", "/api/patient-groups"),
        ("post", "/api/patient-groups"),
        ("patch", "/api/patient-groups/1"),
        ("delete", "/api/patient-groups/1"),
        ("post", "/api/patient-groups/1/members"),
        ("delete", "/api/patient-groups/1/members"),
    ):
        response = client.request(
            method.upper(),
            path,
            json={"name": "Anonymous", "patient_nos": ["P20260001"]},
        )
        assert response.status_code == 401, (method, path)
