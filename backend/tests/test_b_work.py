"""M3 and retained work-module regressions; M4 adapters are injected only in tests."""

from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from io import BytesIO
from time import perf_counter
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlalchemy import func, select
from starlette.websockets import WebSocketDisconnect
from test_auth_grants import client as auth_client
from test_auth_grants import headers, token

from app.health_work import fire_reminders
from app.models import AuditLog, User
from app.work_models import (
    HealthPlan,
    MedicalOrder,
    ReminderLog,
    ReminderRule,
)

client = auth_client


def patient(client):
    response = client.post(
        "/api/patients",
        headers=headers(client),
        json={
            "name": "Consultation test patient",
            "gender": "male",
            "department": "Information Technology",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["patient_no"]


def active_room(client):
    number = patient(client)
    response = client.post(
        "/api/consultations", headers=headers(client), json={"patient_no": number}
    )
    assert response.status_code == 200, response.text
    room_id = response.json()["data"]["id"]
    response = client.post(f"/api/consultations/{room_id}/accept", headers=headers(client, 2))
    assert response.status_code == 200, response.text
    return room_id


def data(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


def receive(ws, kind):
    for _ in range(100):
        message = ws.receive_json()
        if message["type"] == kind:
            return message["data"]
    pytest.fail(f"No {kind} event")


def test_chat_lifecycle_history_and_scope(client):
    id = active_room(client)
    path = f"/api/consultations/{id}"
    h = headers(client)
    for i in range(50):
        data(
            client.post(
                path + "/messages", headers=h, json={"content": f"Message {i}", "client_id": str(i)}
            )
        )
    first = data(client.get(path + "/messages", headers=h))
    assert len(first["items"]) == 20 and first["total"] == 50
    second = data(
        client.get(path + "/messages", headers=h, params={"before_id": first["items"][-1]["id"]})
    )
    third = data(
        client.get(path + "/messages", headers=h, params={"before_id": second["items"][-1]["id"]})
    )
    combined = first["items"] + second["items"] + third["items"]
    assert len({m["id"] for m in combined}) == 50
    assert [m["content"] for m in combined] == [f"Message {i}" for i in reversed(range(50))]
    after = data(client.get(path + "/messages", headers=h, params={"after_id": combined[10]["id"]}))
    assert len(after["items"]) == 10
    replay = data(
        client.post(path + "/messages", headers=h, json={"content": "Message 0", "client_id": "0"})
    )
    assert replay["id"] == combined[-1]["id"]
    assert (
        client.post(
            path + "/messages", headers=h, json={"content": "different", "client_id": "0"}
        ).status_code
        == 409
    )
    assert client.get(path + "/messages", headers=headers(client, 3)).status_code == 404
    with client.app.state.sessions() as db:
        db.get(User, 4).department_id = 1
        db.commit()
    # Accepted conversations are private even within the same department.
    assert client.get(path + "/messages", headers=headers(client, 4)).status_code == 404
    assert (
        client.post(
            path + "/messages", headers=headers(client, 4), json={"content": "No"}
        ).status_code
        == 404
    )
    ended = data(client.post(path + "/end", headers=headers(client, 2)))
    assert ended["status"] == "ended" and ended["ended_at"]
    assert client.post(path + "/messages", headers=h, json={"content": "No"}).status_code == 409
    assert client.post(path + "/accept", headers=h).status_code == 400
    rows = data(client.get("/api/consultations?status=ended", headers=h))["items"]
    assert rows[0]["last_message"] == "Message 49"


def test_websocket_auth_presence_and_reconnect(client):
    id = active_room(client)
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(f"/ws/chat/{id}"):
        pass
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(f"/ws/chat/{id}?token={token(client, 3)}"),
    ):
        pass
    with client.websocket_connect(f"/ws/chat/{id}?token={token(client)}") as a:
        receive(a, "joined")
        with client.websocket_connect(f"/ws/chat/{id}?token={token(client, 2)}") as b:
            receive(b, "joined")
            a.send_json({"type": "message", "data": {"content": "Hello", "client_id": "socket-1"}})
            message = receive(b, "message")
            assert message["content"] == "Hello"
            assert receive(a, "message")["content"] == "Hello"
            assert len(client.app.state.cache.keys(f"chat:presence:{id}:*")) == 2
            assert (
                data(client.get(f"/api/consultations/{id}/messages", headers=headers(client)))[
                    "total"
                ]
                == 1
            )
        a.send_json({"type": "message", "data": {"content": "While away"}})
        receive(a, "message")
    assert not client.app.state.cache.keys(f"chat:presence:{id}:*")
    rows = data(
        client.get(
            f"/api/consultations/{id}/messages?after_id={message['id']}", headers=headers(client, 2)
        )
    )["items"]
    assert [r["content"] for r in rows] == ["While away"]


def test_twenty_live_connections(client):
    id = active_room(client)
    jwt = token(client)
    with ExitStack() as stack:
        sockets = [
            stack.enter_context(client.websocket_connect(f"/ws/chat/{id}?token={jwt}"))
            for _ in range(20)
        ]
        start = perf_counter()
        sockets[0].send_json({"type": "message", "data": {"content": "Twenty connections"}})
        for ws in sockets:
            assert receive(ws, "message")["content"] == "Twenty connections"
        elapsed = (perf_counter() - start) * 1000
        print(f"20 connections persisted broadcast: {elapsed:.1f} ms (FakeRedis/TestClient)")
        assert elapsed < 500


def test_image_validation_storage_and_access(client, tmp_path):
    client.app.state.settings.upload_dir = str(tmp_path / "uploads")
    id = active_room(client)
    h = headers(client)
    buf = BytesIO()
    Image.new("RGB", (32, 32), "blue").save(buf, format="PNG")
    result = data(
        client.post(
            "/api/uploads/images",
            headers=h,
            files={"file": ("../evil.png", buf.getvalue(), "image/png")},
        )
    )
    url = result["url"]
    assert "evil" not in url and ".." not in url
    assert client.get(url).status_code == 401
    assert client.get(url, headers=headers(client, 2)).status_code == 404
    saved = data(
        client.post(f"/api/consultations/{id}/messages", headers=h, json={"image_url": url})
    )
    assert saved["image_url"] == url
    image = client.get(url, headers=headers(client, 2))
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert client.get(url, headers=headers(client, 3)).status_code == 404
    assert (
        client.post(
            "/api/uploads/images",
            headers=h,
            files={"file": ("fake.jpg", b"MZ executable", "image/jpeg")},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/uploads/images",
            headers=h,
            files={"file": ("large.png", b"x" * (5 * 1024 * 1024 + 1), "image/png")},
        ).status_code
        == 413
    )
    assert (
        client.post(
            f"/api/consultations/{id}/messages",
            headers=h,
            json={"image_url": "https://example.test/a.png"},
        ).status_code
        == 422
    )


def plan_body(number):
    return {
        "patient_no": number,
        "title": "Health plan",
        "goals": "Follow-up",
        "start_date": "2026-01-01",
        "end_date": "2027-01-01",
        "entries": [{"kind": "followup", "text": "Weekly visit"}],
    }


def test_plan_reminder_atomic_scope_and_validation(client):
    number = patient(client)
    h = headers(client)
    body = plan_body(number)
    body["new_reminder_rules"] = [
        {"patient_no": number, "title": "Check-in", "rtype": "checkin", "cron_expr": "* * * * *"}
    ]
    plan = data(client.post("/api/legacy/health-plans", headers=h, json=body))
    rules = data(client.get("/api/legacy/reminder-rules", headers=h))
    assert rules[0]["health_plan_id"] == plan["id"]
    assert plan["reminder_rule_ids"] == [rules[0]["id"]]
    assert (
        client.get(f"/api/legacy/health-plans/{plan['id']}", headers=headers(client, 3)).status_code
        == 404
    )
    assert (
        client.post("/api/legacy/health-plans", headers=headers(client, 3), json=body).status_code
        == 404
    )
    assert (
        client.post(
            "/api/legacy/health-plans", headers=h, json={**body, "end_date": "2025-01-01"}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/legacy/reminder-rules/{rules[0]['id']}",
            headers=h,
            json={"cron_expr": "nonsense"},
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/legacy/reminder-rules/{rules[0]['id']}",
            headers=headers(client, 2),
            json={"active": False},
        ).status_code
        == 404
    )
    bad = {
        **body,
        "new_reminder_rules": [{**body["new_reminder_rules"][0], "patient_no": "P-NOT-FOUND"}],
    }
    assert client.post("/api/legacy/health-plans", headers=h, json=bad).status_code == 404
    with client.app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(HealthPlan)) == 1
    changed = data(
        client.patch(
            f"/api/legacy/health-plans/{plan['id']}",
            headers=h,
            json={
                **plan_body(number),
                "status": "completed",
                "entries": [{"kind": "followup", "text": "Weekly visit", "done": True}],
            },
        )
    )
    assert changed["entries"][0]["done"] and changed["status"] == "completed"


def test_reminder_idempotency_read_and_disable(client):
    number = patient(client)
    h = headers(client)
    rule = data(
        client.post(
            "/api/legacy/reminder-rules",
            headers=h,
            json={
                "patient_no": number,
                "title": "Medication",
                "rtype": "medication",
                "cron_expr": "* * * * *",
            },
        )
    )
    start = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(3):
        fire_reminders(client.app.state.sessions, at=start)
    fire_reminders(client.app.state.sessions, at=start + timedelta(minutes=1))
    assert data(client.get("/api/legacy/reminders/unread-count", headers=h))["unread_count"] == 2
    assert (
        data(client.get("/api/legacy/reminders/unread-count", headers=headers(client, 2)))[
            "unread_count"
        ]
        == 0
    )
    peek = data(client.get("/api/legacy/reminders?unread_only=true", headers=h))
    assert peek["unread_count"] == 2 and not peek["items"][0]["read"]
    logs = data(client.get("/api/legacy/reminders", headers=h))
    assert logs["unread_count"] == 0 and all(row["read"] for row in logs["items"])
    assert data(client.post(f"/api/legacy/reminders/{logs['items'][0]['id']}/done", headers=h))[
        "done"
    ]
    data(
        client.patch(f"/api/legacy/reminder-rules/{rule['id']}", headers=h, json={"active": False})
    )
    fire_reminders(client.app.state.sessions, at=start + timedelta(minutes=2))
    with client.app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ReminderLog)) == 2
    assert "legacy_health_reminders" in [job.id for job in client.app.state.scheduler.get_jobs()]


def test_reminder_plan_dates_and_termination(client):
    number = patient(client)
    h = headers(client)
    body = plan_body(number)
    body["new_reminder_rules"] = [
        {"patient_no": number, "title": "Morning", "rtype": "medication", "cron_expr": "0 9 * * *"}
    ]
    plan = data(client.post("/api/legacy/health-plans", headers=h, json=body))
    with client.app.state.sessions() as db:
        rule = db.get(ReminderRule, plan["reminder_rule_ids"][0])
        rule.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        db.commit()
    at = datetime(2026, 9, 13, 1, 0, tzinfo=UTC)
    fire_reminders(client.app.state.sessions, at=at)
    assert data(client.get("/api/legacy/reminders?unread_only=true", headers=h))["total"] == 1
    data(
        client.patch(
            f"/api/legacy/health-plans/{plan['id']}",
            headers=h,
            json={**plan_body(number), "status": "terminated"},
        )
    )
    fire_reminders(client.app.state.sessions, at=at + timedelta(days=1))
    assert data(client.get("/api/legacy/reminders?unread_only=true", headers=h))["total"] == 1


def test_orders_dependency_lifecycle_and_whole_batch_block(client):
    number = patient(client)
    h = headers(client)
    from app.models import Patient

    with client.app.state.sessions() as db:
        pid = db.scalar(select(Patient.id).where(Patient.patient_no == number))
    body = {"record_id": 10, "items": [{"order_type": "drug", "drug_code": "TEST", "dose": "20mg"}]}
    assert client.post("/api/legacy/emr/orders", headers=h, json=body).status_code == 503
    record = SimpleNamespace(patient_id=pid, status="draft")
    client.app.state.order_record_loader = lambda db, id: record if id == 10 else None
    assert (
        client.post(
            "/api/legacy/emr/orders", headers=h, json={**body, "record_id": 999}
        ).status_code
        == 404
    )
    assert client.post("/api/legacy/emr/orders", headers=h, json=body).status_code == 503
    assert (
        client.post(
            "/api/legacy/emr/orders",
            headers=h,
            json={**body, "items": [{"order_type": "drug", "drug_code": "TEST"}]},
        ).status_code
        == 422
    )
    client.app.state.order_validator = lambda db, pid, items: {
        "overall": "passed",
        "results": [{"index": i, "status": "passed", "reasons": []} for i in range(len(items))],
    }
    row = data(client.post("/api/legacy/emr/orders", headers=h, json=body))[0]
    modified = data(
        client.patch(
            f"/api/legacy/emr/orders/{row['id']}",
            headers=h,
            json={**body["items"][0], "dose": "40mg"},
        )
    )
    assert modified["content_json"]["dose"] == "40mg"
    assert (
        data(client.post(f"/api/legacy/emr/orders/{row['id']}/stop", headers=h))["status"]
        == "stopped"
    )
    client.app.state.order_validator = lambda db, pid, items: {
        "overall": "blocked",
        "results": [
            {"index": i, "status": "passed" if i == 0 else "blocked", "reasons": []}
            for i in range(len(items))
        ],
    }
    assert (
        client.post(
            "/api/legacy/emr/orders", headers=h, json={**body, "items": body["items"] * 2}
        ).status_code
        == 409
    )
    record.status = "archived"
    assert client.post("/api/legacy/emr/orders", headers=h, json=body).status_code == 409
    with client.app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(MedicalOrder)) == 1
        actions = set(db.scalars(select(AuditLog.action)))
        assert {
            "medical_order.create",
            "medical_order.modify",
            "medical_order.stop",
            "medical_order.blocked",
        } <= actions
