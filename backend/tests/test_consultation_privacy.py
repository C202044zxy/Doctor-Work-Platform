"""Department search and consultation ownership must apply to every read path."""

import csv
import io

import pytest
from PIL import Image
from starlette.websockets import WebSocketDisconnect
from test_auth_grants import client as auth_client
from test_auth_grants import headers, token
from test_b_work import data

from app.models import User

client = auth_client


def make_patient(client, name, department):
    return data(
        client.post(
            "/api/patients",
            headers=headers(client),
            json={"name": name, "gender": "unknown", "department": department},
        )
    )["patient_no"]


@pytest.mark.parametrize("user_id", [3, 4])
def test_patient_name_search_and_department_scope(client, user_id):
    own = make_patient(client, "Alex Chen", "Cardiology")
    duplicate = make_patient(client, "Alex Chen", "Cardiology")
    foreign = make_patient(client, "Alex Chen", "Information Technology")
    auth = headers(client, user_id)
    for params in ({}, {"name": "lex"}, {"name": "Alex", "size": 1, "page": 2}):
        result = data(client.get("/api/patients", headers=auth, params=params))
        assert result["total"] == 2
        assert {p["patient_no"] for p in result["items"]} <= {own, duplicate}
    for params in (
        {"name": "Nobody"},
        {"name": "%"},
        {"name": "_"},
        {"patient_no": foreign},
        {"name": "Alex", "department": "Information Technology"},
    ):
        assert data(client.get("/api/patients", headers=auth, params=params))["total"] == 0
    assert client.get(f"/api/patients/{foreign}", headers=auth).status_code == 404
    assert (
        client.post("/api/consultations", headers=auth, json={"patient_no": foreign}).status_code
        == 404
    )


def test_waiting_queue_then_private_conversation_including_images_and_export(client, tmp_path):
    # Admin creates this room as the patient-assisting side. Doctor 2 accepts it.
    # Doctor 4 is a different doctor in the same department; doctor 3 is outside it.
    with client.app.state.sessions() as db:
        db.get(User, 4).department_id = 1
        db.commit()
    number = make_patient(client, "Private patient", "Information Technology")
    room = data(
        client.post("/api/consultations", headers=headers(client), json={"patient_no": number})
    )
    path = f"/api/consultations/{room['id']}"
    assert room["status"] == "waiting" and room["doctor_id"] is None
    for user_id in (1, 2, 4):
        rows = data(
            client.get("/api/consultations?status=waiting", headers=headers(client, user_id))
        )
        assert rows["total"] == 1
        assert client.get(path, headers=headers(client, user_id)).status_code == 200
    assert data(client.get("/api/consultations", headers=headers(client, 3)))["total"] == 0
    assert client.post(path + "/accept", headers=headers(client, 3)).status_code == 404
    assert (
        client.post(
            path + "/messages", headers=headers(client), json={"content": "early"}
        ).status_code
        == 409
    )
    accepted = data(client.post(path + "/accept", headers=headers(client, 2)))
    assert accepted["status"] == "active" and accepted["doctor_id"] == 2
    # A stale waiting card cannot steal an already accepted consultation.
    assert client.post(path + "/accept", headers=headers(client, 4)).status_code == 404

    client.app.state.settings.upload_dir = str(tmp_path / "uploads")
    content = io.BytesIO()
    Image.new("RGB", (10, 10)).save(content, format="PNG")
    image = data(
        client.post(
            "/api/uploads/images",
            headers=headers(client),
            files={"file": ("scan.png", content.getvalue(), "image/png")},
        )
    )["url"]
    data(
        client.post(
            path + "/messages",
            headers=headers(client),
            json={"content": "Private message", "image_url": image},
        )
    )

    for state in ("active", "ended"):
        if state == "ended":
            data(client.post(path + "/end", headers=headers(client, 2)))
        for user_id in (3, 4):
            auth = headers(client, user_id)
            for url in (path, path + "/messages", path + "/calls", image):
                assert client.get(url, headers=auth).status_code == 404
            for url in (
                "/api/consultations",
                f"/api/consultations?status={state}",
                "/api/consultations/records?q=Private",
            ):
                assert data(client.get(url, headers=auth))["total"] == 0
            exported = client.get("/api/consultations/export", headers=auth)
            assert exported.status_code == 200
            assert list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig")))) == []
            assert (
                client.post(
                    path + "/messages", headers=auth, json={"content": "blocked"}
                ).status_code
                == 404
            )
            assert client.post(path + "/end", headers=auth).status_code == 404
            with (
                pytest.raises(WebSocketDisconnect),
                client.websocket_connect(f"/ws/chat/{room['id']}?token={token(client, user_id)}"),
            ):
                pass
        for user_id in (1, 2):
            auth = headers(client, user_id)
            assert (
                data(client.get(f"/api/consultations?status={state}", headers=auth))["total"] == 1
            )
            assert (
                data(client.get("/api/consultations/records?q=Private", headers=auth))["total"] == 1
            )
            for url in (path, path + "/messages", path + "/calls", image):
                assert client.get(url, headers=auth).status_code == 200


def test_unrelated_admin_cannot_read_an_accepted_conversation(client):
    number = make_patient(client, "Private patient", "Cardiology")
    room = data(
        client.post("/api/consultations", headers=headers(client, 3), json={"patient_no": number})
    )
    path = f"/api/consultations/{room['id']}"
    data(client.post(path + "/accept", headers=headers(client, 4)))
    assert client.get(path, headers=headers(client)).status_code == 404
    assert data(client.get("/api/consultations", headers=headers(client)))["total"] == 0
    assert client.get(path, headers=headers(client, 3)).status_code == 200
    assert client.get(path, headers=headers(client, 4)).status_code == 200
