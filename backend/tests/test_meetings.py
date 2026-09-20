"""M5 acceptance: the consultation state machine, materials and the report.

The eight scenarios in `docs/02-测试场景.md` §2.6, exercised against a real
SQLite database built by Alembic -- so the tables, the unique keys and the
grant expiry scan are the real ones, not stubs.

The cast is the demo cast: `dr_wang` is a junior in Cardiology (T30 S1 has a
junior initiate), `dr_chen` a senior in Neurology (outside the patient's
department, so his access can only come from the automatic grant), and user 5
a Cardiology colleague who never took part.
"""

from datetime import UTC, datetime, timedelta

import fakeredis
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import hash_password, issue_token
from app.config import Settings
from app.grants import expire_grants
from app.main import create_app
from app.models import (
    AuditLog,
    Department,
    Meeting,
    MeetingMaterial,
    MeetingReport,
    Role,
    TempGrant,
    User,
)
from app.seed import seed


@pytest.fixture
def client(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'meetings.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    seed()
    app = create_app(
        Settings(
            database_url=url,
            redis_url=None,
            scheduler_enabled=False,
            upload_dir=str(tmp_path / "uploads"),
            _env_file=None,
        )
    )
    app.state.cache = fakeredis.FakeRedis()
    with app.state.sessions() as db:
        roles = {r.name: r.id for r in db.scalars(select(Role))}
        departments = list(db.scalars(select(Department).order_by(Department.id)))
        for index, (name, role, dept) in enumerate(
            [
                ("admin", "admin", 0),
                ("dr_li", "senior", 1),
                ("dr_wang", "junior", 1),
                ("dr_chen", "senior", 2),
                ("colleague", "senior", 1),
                ("neurologist", "senior", 2),
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


PATIENT_NO = "P20260001"
PURPOSE = "Confirm the diuretic dose before discharge."


def headers(client, user_id=3):
    with client.app.state.sessions() as db:
        token = issue_token(db.get(User, user_id), client.app.state.settings.jwt_secret)
    return {"Authorization": f"Bearer {token}"}


def create_patient(client, user_id=2, department="Cardiology", name="Zhao Dayong"):
    response = client.post(
        "/api/patients",
        headers=headers(client, user_id),
        json={"name": name, "gender": "male", "department": department},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["patient_no"]


def invite(client, actor=3, invitees=(4,), patient_no=PATIENT_NO, **overrides):
    body = {
        "patient_no": patient_no,
        "participant_ids": list(invitees),
        "purpose": PURPOSE,
    }
    body.update(overrides)
    return client.post("/api/meetings", headers=headers(client, actor), json=body)


def meeting_id(client, actor=3, invitees=(4,), **overrides):
    response = invite(client, actor=actor, invitees=invitees, **overrides)
    assert response.status_code == 200, response.text
    return response.json()["data"]["id"]


def accept(client, mid, actor=4):
    return client.post(f"/api/meetings/{mid}/accept", headers=headers(client, actor))


def start(client, mid, actor=3):
    return client.post(f"/api/meetings/{mid}/start", headers=headers(client, actor))


def complete(client, mid, actor=3):
    return client.post(f"/api/meetings/{mid}/complete", headers=headers(client, actor))


def upload(client, mid, actor=3, filename="心电图-2026-09-01.pdf"):
    return client.post(
        f"/api/meetings/{mid}/materials",
        headers=headers(client, actor),
        files={"file": (filename, b"%PDF-1.4\nECG strip\n", "application/pdf")},
    )


def report_body(count=3):
    return {
        "expert_opinions": [
            {"expert_id": 4, "expert_name": "dr_chen", "opinion": "Reduce the diuretic."},
            {"expert_id": 2, "expert_name": "dr_li", "opinion": "Review renal function."},
            {"expert_id": 5, "expert_name": "colleague", "opinion": "No objection."},
        ][:count],
        "conclusion": "Halve the diuretic dose and review in one week.",
    }


def test_meeting_creation_creates_the_grant_and_opens_the_patient(client):
    """M5-T1. A junior may initiate, and each invitee gets the automatic grant."""
    create_patient(client)
    before = client.get(f"/api/patients/{PATIENT_NO}", headers=headers(client, 4))
    assert before.status_code == 404  # Outside the patient's department.

    scheduled = datetime.now(UTC) + timedelta(hours=2)
    response = invite(client, scheduled_at=scheduled.isoformat())
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "requested"
    assert data["purpose"] == PURPOSE  # 必填且能读回.
    assert data["patient_no"] == PATIENT_NO
    assert data["initiator_id"] == 3
    assert [row["status"] for row in data["participants"]] == ["invited"]
    # Floating point is not involved, but the JSON round trip loses the offset
    # on some drivers, so compare to the second.
    assert abs(datetime.fromisoformat(data["scheduled_at"]) - scheduled) < timedelta(seconds=1)

    with client.app.state.sessions() as db:
        grants = list(db.scalars(select(TempGrant).where(TempGrant.grantee_id == 4)))
    assert len(grants) == 1
    assert grants[0].patient_id == db_patient_id(client)
    assert grants[0].granted_by == 3
    expire_at = grants[0].expire_at.replace(tzinfo=UTC)
    assert abs(expire_at - (scheduled + timedelta(hours=24))) < timedelta(seconds=1)

    assert client.get(f"/api/patients/{PATIENT_NO}", headers=headers(client, 4)).status_code == 200


def test_scheduled_at_defaults_to_now_when_omitted(client):
    """M5-01's three inputs are patient + experts + purpose; a client that sends
    no time must still succeed, and the response reports what was stored."""
    create_patient(client)
    data = invite(client).json()["data"]
    assert data["scheduled_at"] is not None
    with client.app.state.sessions() as db:
        grant = db.scalar(select(TempGrant).where(TempGrant.grantee_id == 4))
    # The grant window is therefore bounded even though no time was sent.
    assert grant.expire_at.replace(tzinfo=UTC) > datetime.now(UTC) + timedelta(hours=23)


def test_missing_purpose_is_a_422_naming_the_field(client):
    """M5-T3, second half."""
    create_patient(client)
    response = client.post(
        "/api/meetings",
        headers=headers(client, 3),
        json={"patient_no": PATIENT_NO, "participant_ids": [4]},
    )
    assert response.status_code == 422
    assert "purpose" in response.json()["message"]

    blank = invite(client, purpose="   ")
    assert blank.status_code == 422
    assert "purpose" in blank.json()["message"]


def test_unknown_invitee_is_a_404(client):
    create_patient(client)
    assert invite(client, invitees=(999,)).status_code == 404


def test_invitation_inbox_accept_decline_and_grant_access(client):
    """M5-T2, plus the inbox the frontend renders."""
    create_patient(client)
    mid = meeting_id(client)

    # 邀请箱: the invitee sees the meeting without a patient filter, and sees
    # the meeting's purpose so the inbox can show it.
    listed = client.get("/api/meetings", headers=headers(client, 4)).json()["data"]
    assert [row["id"] for row in listed["items"]] == [mid]
    assert listed["items"][0]["purpose"] == PURPOSE
    # An unrelated physician sees nothing.
    assert client.get("/api/meetings", headers=headers(client, 5)).json()["data"]["total"] == 0

    assert accept(client, mid).status_code == 200
    detail = client.get(f"/api/meetings/{mid}", headers=headers(client, 4)).json()["data"]
    assert detail["status"] == "accepted"
    assert [row["status"] for row in detail["participants"]] == ["accepted"]
    assert client.get(f"/api/patients/{PATIENT_NO}", headers=headers(client, 4)).status_code == 200

    # Answering twice is a 409, not a second state change.
    assert accept(client, mid).status_code == 409

    # The initiator is not an invitee, so the invitation action is not theirs.
    other = meeting_id(client, actor=3, invitees=(4,))
    assert accept(client, other, actor=3).status_code == 403
    assert (
        client.post(f"/api/meetings/{other}/decline", headers=headers(client, 2)).status_code == 403
    )


def test_declining_is_a_state_not_a_deletion(client):
    create_patient(client)
    mid = meeting_id(client)
    response = client.post(f"/api/meetings/{mid}/decline", headers=headers(client, 4))
    assert response.status_code == 200
    data = response.json()["data"]
    # Every invitee refused, so the machine's declined branch is the answer.
    assert data["status"] == "declined"
    assert data["participants"][0]["status"] == "declined"
    assert client.get(f"/api/meetings/{mid}", headers=headers(client, 4)).status_code == 200


def test_illegal_transitions_are_409(client):
    """M5-T3. `requested` straight to `completed` must be refused as a conflict."""
    create_patient(client)
    mid = meeting_id(client)
    assert complete(client, mid).status_code == 409
    assert start(client, mid).status_code == 409  # accept first.
    assert accept(client, mid).status_code == 200
    assert complete(client, mid).status_code == 409  # not started yet.
    assert start(client, mid).status_code == 200
    assert start(client, mid).status_code == 409  # already running.
    assert complete(client, mid).status_code == 200
    with client.app.state.sessions() as db:
        meeting = db.get(Meeting, mid)
    assert meeting.status == "completed"
    assert meeting.started_at is not None and meeting.completed_at is not None


def test_state_changes_are_audited(client):
    create_patient(client)
    mid = meeting_id(client)
    accept(client, mid)
    with client.app.state.sessions() as db:
        actions = [row.action for row in db.scalars(select(AuditLog))]
    assert actions.count("meeting.create") == 1
    assert actions.count("meeting.accept") == 1
    # The automatic grant leaves its own trail row, the same one the T10
    # endpoint writes.
    assert actions.count("temp_grant.create") == 1


def test_non_participant_is_refused_without_leaking_existence(client):
    create_patient(client)
    mid = meeting_id(client)
    assert client.get(f"/api/meetings/{mid}", headers=headers(client, 5)).status_code == 404
    assert (
        client.get(f"/api/meetings/{mid}/participants", headers=headers(client, 5)).status_code
        == 404
    )
    assert client.get("/api/meetings/999999", headers=headers(client, 3)).status_code == 404
    # Materials and the report are 403: the caller is holding a real URL.
    assert (
        client.get(f"/api/meetings/{mid}/materials", headers=headers(client, 5)).status_code == 403
    )
    assert (
        client.post(
            f"/api/meetings/{mid}/report", headers=headers(client, 5), json=report_body()
        ).status_code
        == 403
    )


def test_every_meeting_route_needs_a_token(client):
    create_patient(client)
    mid = meeting_id(client)
    for path in (
        "/api/meetings",
        f"/api/meetings/{mid}",
        f"/api/meetings/{mid}/participants",
        f"/api/meetings/{mid}/materials",
        f"/api/meetings/{mid}/report",
    ):
        assert client.get(path).status_code == 401


def test_material_upload_share_and_download_keeps_the_chinese_name(client):
    """M5-T4."""
    create_patient(client)
    mid = meeting_id(client)
    accept(client, mid)
    start(client, mid)

    response = upload(client, mid)
    assert response.status_code == 200, response.text
    material = response.json()["data"]
    assert material["filename"] == "心电图-2026-09-01.pdf"
    assert material["content_type"] == "application/pdf"
    assert material["uploaded_by"] == 3

    # Visible to the other participant straight away.
    listed = client.get(f"/api/meetings/{mid}/materials", headers=headers(client, 4))
    assert [row["filename"] for row in listed.json()["data"]] == ["心电图-2026-09-01.pdf"]

    download = client.get(f"/api/materials/{material['id']}/download", headers=headers(client, 4))
    assert download.status_code == 200
    assert download.content == b"%PDF-1.4\nECG strip\n"
    disposition = download.headers["content-disposition"]
    assert "attachment" in disposition
    assert "filename*=UTF-8''" in disposition
    assert "%E5%BF%83%E7%94%B5%E5%9B%BE" in disposition  # 心电图, UTF-8, percent-encoded

    with client.app.state.sessions() as db:
        stored = db.scalar(select(MeetingMaterial).where(MeetingMaterial.id == material["id"]))
    # The name on disk is randomised and carries no trace of the client's.
    assert "心" not in stored.stored_name
    assert stored.stored_name.endswith(".pdf")


def test_non_participant_download_is_403(client):
    """M5-T5. The check has to be on the server, not in the UI."""
    create_patient(client)
    mid = meeting_id(client)
    material = upload(client, mid).json()["data"]
    assert (
        client.get(
            f"/api/materials/{material['id']}/download", headers=headers(client, 5)
        ).status_code
        == 403
    )
    assert client.get(f"/api/materials/{material['id']}/download").status_code == 401
    assert (
        client.get("/api/materials/999999/download", headers=headers(client, 3)).status_code == 404
    )


def test_upload_whitelist_is_wider_than_the_image_one_and_names_bad_types(client):
    """T31 §3: the component is shared, the whitelist is not. A PDF must pass
    where T26's image-only list refuses it, and an executable must not."""
    create_patient(client)
    mid = meeting_id(client)
    assert upload(client, mid).status_code == 200

    rejected = client.post(
        f"/api/meetings/{mid}/materials",
        headers=headers(client, 3),
        files={"file": ("payload.sh", b"#!/bin/sh\n", "application/x-sh")},
    )
    assert rejected.status_code == 422
    assert "application/x-sh" in rejected.json()["message"]

    # An image still passes: the wider list is a superset, not a replacement.
    image = client.post(
        f"/api/meetings/{mid}/materials",
        headers=headers(client, 3),
        files={"file": ("scan.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    assert image.status_code == 200


def test_report_archives_to_the_patient_and_versions_do_not_overwrite(client):
    """M5-T6 and M5-T7."""
    create_patient(client)
    mid = meeting_id(client)
    accept(client, mid)
    start(client, mid)

    early = client.post(
        f"/api/meetings/{mid}/report", headers=headers(client, 3), json=report_body()
    )
    assert early.status_code == 409  # Not completed yet.

    assert complete(client, mid).status_code == 200
    saved = client.post(
        f"/api/meetings/{mid}/report", headers=headers(client, 3), json=report_body()
    )
    assert saved.status_code == 200, saved.text
    first = saved.json()["data"]
    assert first["version"] == 1
    assert len(first["expert_opinions"]) == 3
    assert first["conclusion"].startswith("Halve the diuretic")

    # A later change is a new version; the first stays readable.
    second = client.post(
        f"/api/meetings/{mid}/report",
        headers=headers(client, 3),
        json={**report_body(), "conclusion": "Reduce to 20 mg/day and review in a week."},
    ).json()["data"]
    assert second["version"] == 2
    latest = client.get(f"/api/meetings/{mid}/report", headers=headers(client, 3)).json()["data"]
    assert latest["version"] == 2
    assert latest["conclusion"] != first["conclusion"]
    older = client.get(
        f"/api/meetings/{mid}/report", params={"version": 1}, headers=headers(client, 3)
    ).json()["data"]
    assert older["conclusion"] == first["conclusion"]
    with client.app.state.sessions() as db:
        assert db.scalar(select(MeetingReport).where(MeetingReport.meeting_id == mid)) is not None

    # M5-T7: the "会诊记录" tab's data path -- a same-department colleague who
    # neither started nor attended the meeting still reads the report back.
    listed = client.get(
        "/api/meetings", params={"patient_no": PATIENT_NO}, headers=headers(client, 5)
    ).json()["data"]
    assert [row["id"] for row in listed["items"]] == [mid]
    read_back = client.get(f"/api/meetings/{mid}/report", headers=headers(client, 5))
    assert read_back.status_code == 200
    assert read_back.json()["data"]["conclusion"] == latest["conclusion"]

    # But writing it stays participants-only (T32 S2).
    assert (
        client.post(
            f"/api/meetings/{mid}/report", headers=headers(client, 5), json=report_body()
        ).status_code
        == 403
    )

    # A patient-scoped list outside the caller's department is an empty page,
    # not a 403. (`user 1` would not show this: an administrator holds
    # `data.all`, so every patient is inside their scope by definition.)
    outside = client.get(
        "/api/meetings", params={"patient_no": PATIENT_NO}, headers=headers(client, 6)
    ).json()["data"]
    assert outside["items"] == []


def test_printable_sheet_is_a4_html_and_participants_only(client):
    """M5-T6, second half: the Jinja2 sheet exists and is print-sized."""
    create_patient(client)
    mid = meeting_id(client)
    accept(client, mid)
    start(client, mid)
    complete(client, mid)
    client.post(f"/api/meetings/{mid}/report", headers=headers(client, 3), json=report_body())

    sheet = client.get(f"/api/meetings/{mid}/report/print", headers=headers(client, 3))
    assert sheet.status_code == 200
    assert sheet.headers["content-type"].startswith("text/html")
    assert "size: A4" in sheet.text
    assert "@media print" in sheet.text
    assert "Halve the diuretic dose" in sheet.text
    assert "dr_chen" in sheet.text  # every expert's opinion is attributed
    assert f"RC-{mid:05d}-v1" in sheet.text

    assert (
        client.get(f"/api/meetings/{mid}/report/print", headers=headers(client, 5)).status_code
        == 403
    )


def test_grant_expiry_makes_the_patient_404_again(client):
    """M5-T8. The grant is the only thing that opened the patient, so its
    expiry closes it again."""
    create_patient(client)
    mid = meeting_id(client)
    assert client.get(f"/api/patients/{PATIENT_NO}", headers=headers(client, 4)).status_code == 200

    with client.app.state.sessions() as db:
        grant = db.scalar(select(TempGrant).where(TempGrant.grantee_id == 4))
        grant.expire_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
    expire_grants(client.app.state.sessions)
    with client.app.state.sessions() as db:
        assert db.get(TempGrant, grant.id).is_valid is False

    assert client.get(f"/api/patients/{PATIENT_NO}", headers=headers(client, 4)).status_code == 404
    # The meeting itself is untouched -- the report stays archived (no
    # `archived` state on the meeting, only the report remains readable).
    assert client.get(f"/api/meetings/{mid}", headers=headers(client, 4)).status_code == 200


def test_doctor_directory_feeds_the_invite_picker(client):
    """The picker's directory: authenticated, identity only, no email."""
    body = client.get("/api/meetings/doctors", headers=headers(client, 3)).json()["data"]
    names = [row["name"] for row in body["items"]]
    assert {"dr_chen", "dr_wang", "colleague"} <= set(names)
    assert set(body["items"][0]) == {"id", "username", "name", "title", "department"}
    filtered = client.get(
        "/api/meetings/doctors", params={"q": "chen"}, headers=headers(client, 3)
    ).json()["data"]
    assert [row["name"] for row in filtered["items"]] == ["dr_chen"]
    assert client.get("/api/meetings/doctors").status_code == 401


def db_patient_id(client):
    from app.models import Patient

    with client.app.state.sessions() as db:
        return db.scalar(select(Patient.id).where(Patient.patient_no == PATIENT_NO))
