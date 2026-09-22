"""M5 reusing M3's room: one socket, one history, one signaling path.

`docs/api/API-索引.md` requires consultations and meetings to share
`/ws/chat/{room_id}` rather than each opening one of their own, and
`docs/02-测试场景.md` flow 2 step 4 walks the meeting chat room. This module exercises
that room against a real Alembic-built SQLite database, so the room keys, the retry key
and the call log are the real ones rather than stubs.

The cast is `test_meetings.py`'s: `dr_wang` (3) initiates as a junior, `dr_chen` (4) is
the invited expert from another department, `colleague` (5) is a Cardiology senior who
is not in the meeting unless a test invites him.
"""

import io

import fakeredis
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from app.auth import hash_password, issue_token
from app.config import Settings
from app.main import create_app
from app.models import Department, Role, User
from app.seed import seed
from app.work_models import CallLog, ConsultMessage


# A real PNG, built rather than pasted: the upload path decodes and re-encodes every
# image, so a hand-written byte string with a bad CRC would exercise the wrong failure.
def _png():
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
    return buffer.getvalue()


PNG = _png()


@pytest.fixture
def client(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm5room.db'}"
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


def ws_token(client, user_id=3):
    with client.app.state.sessions() as db:
        return issue_token(db.get(User, user_id), client.app.state.settings.jwt_secret)


def receive(ws, kind):
    for _ in range(100):
        message = ws.receive_json()
        if message["type"] == kind:
            return message["data"]
    pytest.fail(f"No {kind} event")


def create_patient(client, user_id=2, department="Cardiology", name="Zhao Dayong"):
    response = client.post(
        "/api/patients",
        headers=headers(client, user_id),
        json={"name": name, "gender": "male", "department": department},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["patient_no"]


def meeting(client, actor=3, invitees=(4,)):
    response = client.post(
        "/api/meetings",
        headers=headers(client, actor),
        json={
            "patient_no": PATIENT_NO,
            "participant_ids": list(invitees),
            "purpose": PURPOSE,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["id"]


def started_meeting(client, invitees=(4,), patient=True):
    """A meeting an expert has accepted and the initiator has started."""
    if patient:
        create_patient(client)
    mid = meeting(client, invitees=invitees)
    assert client.post(f"/api/meetings/{mid}/accept", headers=headers(client, 4)).status_code == 200
    assert client.post(f"/api/meetings/{mid}/start", headers=headers(client, 3)).status_code == 200
    return mid


def consultation(client):
    """An active patient consultation, for the namespace-collision test."""
    response = client.post(
        "/api/consultations", headers=headers(client, 2), json={"patient_no": PATIENT_NO}
    )
    assert response.status_code == 200, response.text
    room = response.json()["data"]["id"]
    accepted = client.post(f"/api/consultations/{room}/accept", headers=headers(client, 3))
    assert accepted.status_code == 200, accepted.text
    return room


def post(client, path, user_id=3, **body):
    body.setdefault("content", "hello")
    return client.post(path, headers=headers(client, user_id), json=body)


def items(client, path, user_id=3):
    response = client.get(path, headers=headers(client, user_id))
    assert response.status_code == 200, response.text
    return response.json()["data"]["items"]


def test_a_meeting_and_a_consultation_with_the_same_number_are_different_rooms(client):
    """The `m` prefix is the whole point: `1` and `m1` are two rooms, not one."""
    create_patient(client)
    room = consultation(client)
    mid = meeting(client)
    assert room == mid  # Same integer, deliberately: that is the collision being tested.
    # A meeting talks only while it is in progress, so the expert accepts and the
    # initiator starts it before either room is used.
    assert client.post(f"/api/meetings/{mid}/accept", headers=headers(client, 4)).status_code == 200
    assert client.post(f"/api/meetings/{mid}/start", headers=headers(client, 3)).status_code == 200

    first = post(client, f"/api/consultations/{room}/messages", 2, content="patient channel")
    assert first.status_code == 200, first.text
    second = post(client, f"/api/meetings/{mid}/messages", 3, content="colleague channel")
    assert second.status_code == 200, second.text

    consult = [m["content"] for m in items(client, f"/api/consultations/{room}/messages", 2)]
    discuss = [m["content"] for m in items(client, f"/api/meetings/{mid}/messages", 3)]
    assert consult == ["patient channel"]
    assert discuss == ["colleague channel"]

    # The stored rows carry the room they belong to, and only a consultation row can
    # name a consultation.
    with client.app.state.sessions() as db:
        rows = {row.room_key: row.consultation_id for row in db.scalars(select(ConsultMessage))}
    assert rows[str(room)] == room
    assert rows[f"m{mid}"] is None


def test_room_keys_that_name_nothing_are_refused(client):
    create_patient(client)
    assert client.get("/api/meetings/999/messages", headers=headers(client)).status_code == 404
    assert post(client, "/api/meetings/999/messages").status_code == 404
    # A key that is neither digits nor `m<digits>` is refused rather than guessed at.
    for key in ("x1", "m0", "m-3", "1x"):
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(f"/ws/chat/{key}?token={ws_token(client)}"),
        ):
            pass


def test_only_participants_may_enter_the_meeting_room(client):
    create_patient(client)
    mid = meeting(client)
    # `colleague` (5) is not invited: refused on the reads and the writes, and on the
    # socket before it ever upgrades.
    assert (
        client.get(f"/api/meetings/{mid}/messages", headers=headers(client, 5)).status_code == 403
    )
    assert post(client, f"/api/meetings/{mid}/messages", 5).status_code == 403
    assert client.get(f"/api/meetings/{mid}/calls", headers=headers(client, 5)).status_code == 403
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(f"/ws/chat/m{mid}?token={ws_token(client, 5)}"),
    ):
        pass


def test_messages_are_only_accepted_while_the_meeting_is_in_progress(client):
    create_patient(client)
    mid = meeting(client)
    assert client.post(f"/api/meetings/{mid}/accept", headers=headers(client, 4)).status_code == 200
    # `requested` -> `accepted`: still no conversation.
    assert post(client, f"/api/meetings/{mid}/messages").status_code == 409
    assert post(client, f"/api/meetings/{mid}/messages", 4).status_code == 409

    assert client.post(f"/api/meetings/{mid}/start", headers=headers(client, 3)).status_code == 200
    sent = post(client, f"/api/meetings/{mid}/messages", 4, content="Reduce the diuretic")
    assert sent.status_code == 200, sent.text

    done = client.post(f"/api/meetings/{mid}/complete", headers=headers(client, 3))
    assert done.status_code == 200, done.text
    assert post(client, f"/api/meetings/{mid}/messages").status_code == 409
    # Read-only after the end, not erased: the transcript is what the report is written
    # from.
    assert [m["content"] for m in items(client, f"/api/meetings/{mid}/messages")] == [
        "Reduce the diuretic"
    ]


def test_meeting_messages_round_trip_and_retry_idempotently(client):
    create_patient(client)
    mid = started_meeting(client, patient=False)
    path = f"/api/meetings/{mid}/messages"
    assert post(client, path, 3, content="Shall we halve it?", client_id="k1").status_code == 200
    assert post(client, path, 4, content="Agreed.", client_id="k2").status_code == 200
    # Resending the same key and body returns the same row rather than a second one.
    assert post(client, path, 3, content="Shall we halve it?", client_id="k1").status_code == 200
    # The same key with different content is a conflict, not a silent overwrite.
    assert post(client, path, 3, content="Something else", client_id="k1").status_code == 409

    rows = items(client, path)
    # Newest first: the same descending page M3's history answers with.
    assert [row["content"] for row in rows] == ["Agreed.", "Shall we halve it?"]
    assert [row["room_key"] for row in rows] == [f"m{mid}", f"m{mid}"]
    assert [row["sender_type"] for row in rows] == ["doctor", "doctor"]


def test_a_message_over_the_shared_socket_reaches_the_meeting_room(client):
    create_patient(client)
    mid = started_meeting(client, patient=False)
    key = f"m{mid}"
    with client.websocket_connect(f"/ws/chat/{key}?token={ws_token(client, 3)}") as a:
        receive(a, "joined")
        with client.websocket_connect(f"/ws/chat/{key}?token={ws_token(client, 4)}") as b:
            receive(b, "joined")
            a.send_json(
                {"type": "message", "data": {"content": "over the socket", "client_id": "s1"}}
            )
            assert receive(b, "message")["content"] == "over the socket"
    assert [row["content"] for row in items(client, f"/api/meetings/{mid}/messages")] == [
        "over the socket"
    ]


def test_an_upload_bound_to_a_consultation_cannot_be_sent_into_a_meeting(client):
    create_patient(client)
    room = consultation(client)
    mid = started_meeting(client, patient=False)
    upload = client.post(
        "/api/uploads/images",
        headers=headers(client, 3),
        files={"file": ("scan.png", PNG, "image/png")},
    )
    assert upload.status_code == 200, upload.text
    url = upload.json()["data"]["url"]

    # Bound to the consultation by the first send, so it cannot be replayed elsewhere.
    bound = post(client, f"/api/consultations/{room}/messages", 3, content="", image_url=url)
    assert bound.status_code == 200, bound.text
    assert (
        post(client, f"/api/meetings/{mid}/messages", 3, content="", image_url=url).status_code
        == 422
    )


def test_signaling_in_a_meeting_room_is_recorded_against_the_room(client):
    create_patient(client)
    room = consultation(client)
    mid = started_meeting(client, patient=False)
    key = f"m{mid}"
    sdp = "v=0\r\ns=meeting\r\n"
    with client.websocket_connect(f"/ws/chat/{key}?token={ws_token(client, 3)}") as a:
        receive(a, "joined")
        with client.websocket_connect(f"/ws/chat/{key}?token={ws_token(client, 4)}") as b:
            receive(b, "joined")
            a.send_json({"type": "call_offer", "data": {"call_id": "meeting-call", "sdp": sdp}})
            assert receive(b, "call_offer")["sdp"] == sdp
            b.send_json({"type": "call_answer", "data": {"call_id": "meeting-call", "sdp": sdp}})
            assert receive(a, "call_answer")["sdp"] == sdp
            a.send_json({"type": "call_connected", "data": {"call_id": "meeting-call"}})
            # A message behind it confirms call_connected was processed.
            a.send_json({"type": "message", "data": {"content": "connected"}})
            receive(a, "message")
            b.send_json({"type": "call_end", "data": {"call_id": "meeting-call"}})
            assert receive(a, "call_end")["reason"] == "hangup"

    rows = items(client, f"/api/meetings/{mid}/calls")
    assert len(rows) == 1
    assert rows[0]["room_key"] == key
    assert rows[0]["consultation_id"] is None
    assert rows[0]["connected_at"] is not None
    with client.app.state.sessions() as db:
        row = db.scalar(select(CallLog))
        assert row.room_key == key and row.consultation_id is None
    # A meeting and a consultation of the same number are different rooms, and the call
    # is filed against the meeting alone.
    assert room == mid
    assert items(client, f"/api/consultations/{room}/calls", 2) == []


def test_a_call_connects_two_and_refuses_a_third(client):
    create_patient(client)
    mid = started_meeting(client, invitees=(4, 5), patient=False)
    key = f"m{mid}"
    with client.websocket_connect(f"/ws/chat/{key}?token={ws_token(client, 3)}") as a:
        receive(a, "joined")
        with client.websocket_connect(f"/ws/chat/{key}?token={ws_token(client, 4)}") as b:
            receive(b, "joined")
            with client.websocket_connect(f"/ws/chat/{key}?token={ws_token(client, 5)}") as c:
                receive(c, "joined")
                a.send_json(
                    {"type": "call_offer", "data": {"call_id": "crowded", "sdp": "v=0\r\n"}}
                )
                # No peer is chosen for the caller, and no call is left behind.
                error = receive(a, "error")
                assert "two participants" in error["message"]
                assert not client.app.state.chat.calls


def test_completing_the_meeting_ends_a_live_call(client):
    create_patient(client)
    mid = started_meeting(client, patient=False)
    key = f"m{mid}"
    with client.websocket_connect(f"/ws/chat/{key}?token={ws_token(client, 3)}") as a:
        receive(a, "joined")
        with client.websocket_connect(f"/ws/chat/{key}?token={ws_token(client, 4)}") as b:
            receive(b, "joined")
            a.send_json({"type": "call_offer", "data": {"call_id": "cut-short", "sdp": "v=0\r\n"}})
            receive(b, "call_offer")
            b.send_json({"type": "call_answer", "data": {"call_id": "cut-short", "sdp": "v=0\r\n"}})
            receive(a, "call_answer")
            response = client.post(f"/api/meetings/{mid}/complete", headers=headers(client, 3))
            assert response.status_code == 200, response.text
            assert receive(a, "call_end")["reason"] == "meeting_ended"
            assert receive(b, "call_end")["reason"] == "meeting_ended"

    rows = items(client, f"/api/meetings/{mid}/calls")
    assert [row["end_reason"] for row in rows] == ["meeting_ended"]


def test_completing_the_meeting_tells_its_room(client):
    """The room learns the chat went read-only, without a reload."""
    create_patient(client)
    mid = started_meeting(client, patient=False)
    key = f"m{mid}"
    with client.websocket_connect(f"/ws/chat/{key}?token={ws_token(client, 4)}") as expert:
        receive(expert, "joined")
        complete = client.post(f"/api/meetings/{mid}/complete", headers=headers(client, 3))
        assert complete.status_code == 200, complete.text
        ended = receive(expert, "status")
        assert ended["writable"] is False
        assert ended["status"] == "completed"
