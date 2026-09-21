"""M3 record, call, and cross-branch integration regressions."""

import csv
import io
import logging
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from test_auth_grants import client as auth_client
from test_auth_grants import headers, token
from test_b_work import active_room, data, receive

from app.calls import Signal
from app.logging_utils import RedactWebSocketToken
from app.models import Patient, User
from app.work_models import Consultation

client = auth_client


def test_records_combined_filters_export_scope_and_readonly(client):
    room = active_room(client)
    with client.app.state.sessions() as db:
        row = db.get(Consultation, room)
        row.created_at = datetime(2026, 9, 17, 16, 30, tzinfo=UTC)  # Sep 18 in Shanghai
        db.get(Patient, row.patient_id).name = "Zhao Dayong"
        db.get(User, 4).department_id = 1
        db.commit()
    data(
        client.post(
            f"/api/consultations/{room}/messages",
            headers=headers(client),
            json={"content": "胸痛 = test"},
        )
    )
    filters = {"patient": "Zhao", "q": "胸痛", "from": "2026-09-18", "to": "2026-09-18"}
    result = data(
        client.get("/api/consultations/records", params=filters, headers=headers(client, 2))
    )
    assert result["total"] == 1 and result["items"][0]["is_participant"]
    exported = client.get("/api/consultations/export", params=filters, headers=headers(client, 2))
    assert exported.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert len(rows) == result["total"] and rows[0]["id"] == str(room)
    assert "2026-09-18" in exported.headers["content-disposition"]
    assert (
        data(client.get("/api/consultations/records", params=filters, headers=headers(client, 3)))[
            "total"
        ]
        == 0
    )
    assert (
        data(
            client.get(
                "/api/consultations/records",
                params={**filters, "to": "2026-09-17", "from": "2026-09-17"},
                headers=headers(client),
            )
        )["total"]
        == 0
    )
    assert (
        client.get(
            "/api/consultations/records?from=2026-09-20&to=2026-09-01", headers=headers(client)
        ).status_code
        == 422
    )
    assert (
        client.get(f"/api/consultations/{room}/messages", headers=headers(client, 4)).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/consultations/{room}/messages",
            headers=headers(client, 4),
            json={"content": "blocked"},
        ).status_code
        == 404
    )


def test_csv_neutralizes_formulas_and_keywords_are_literal(client):
    room = active_room(client)
    data(
        client.post(
            f"/api/consultations/{room}/messages", headers=headers(client), json={"content": "=1+1"}
        )
    )
    response = client.get("/api/consultations/export", headers=headers(client))
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert rows[0]["last_message"] == "'=1+1"
    assert (
        data(client.get("/api/consultations/records?q=%25", headers=headers(client)))["total"] == 0
    )


def test_finished_call_contract_idempotency_and_validation(client):
    room = active_room(client)
    path = f"/api/consultations/{room}/calls"
    assert data(client.get(path, headers=headers(client)))["total"] == 0
    ended = datetime.now(UTC) - timedelta(seconds=1)
    body = {
        "call_id": "reported-call",
        "started_at": (ended - timedelta(seconds=65)).isoformat(),
        "connected_at": (ended - timedelta(seconds=60)).isoformat(),
        "ended_at": ended.isoformat(),
        "duration_seconds": 60,
    }
    record = data(client.post(path, headers=headers(client), json=body))
    assert record["duration_seconds"] == 60 and record["ended_at"]
    assert data(client.post(path, headers=headers(client, 2), json=body))["id"] == record["id"]
    assert data(client.get(path, headers=headers(client)))["total"] == 1
    assert (
        client.post(
            path, headers=headers(client), json={**body, "duration_seconds": 999}
        ).status_code
        == 422
    )
    assert (
        client.post(
            path,
            headers=headers(client),
            json={**body, "connected_at": body["ended_at"], "duration_seconds": 0},
        ).status_code
        == 409
    )
    with client.app.state.sessions() as db:
        db.get(User, 4).department_id = 1
        db.commit()
    assert client.post(path, headers=headers(client, 4), json=body).status_code == 404
    assert client.get(path, headers=headers(client, 3)).status_code == 404


@pytest.mark.parametrize("ending,reason", [("call_end", "hangup"), ("call_reject", "rejected")])
def test_signaling_negotiation_and_persisted_end(client, ending, reason):
    room = active_room(client)
    with client.websocket_connect(f"/ws/chat/{room}?token={token(client)}") as a:
        receive(a, "joined")
        with client.websocket_connect(f"/ws/chat/{room}?token={token(client, 2)}") as b:
            receive(b, "joined")
            sdp = "v=0\r\ns=test\r\n"
            a.send_json({"type": "call_offer", "data": {"call_id": "signal-call", "sdp": sdp}})
            assert receive(b, "call_offer")["sdp"] == sdp
            if ending == "call_end":
                b.send_json({"type": "call_answer", "data": {"call_id": "signal-call", "sdp": sdp}})
                assert receive(a, "call_answer")["sdp"] == sdp
                a.send_json(
                    {
                        "type": "ice_candidate",
                        "data": {"call_id": "signal-call", "candidate": {"candidate": "test"}},
                    }
                )
                assert receive(b, "ice_candidate")["candidate"]["candidate"] == "test"
                a.send_json({"type": "call_connected", "data": {"call_id": "signal-call"}})
                # A later message on the same connection confirms call_connected was processed.
                a.send_json({"type": "message", "data": {"content": "connected"}})
                receive(a, "message")
            b.send_json({"type": ending, "data": {"call_id": "signal-call"}})
            assert receive(a, "call_end")["reason"] == reason
            assert receive(b, "call_end")["reason"] == reason
    rows = data(client.get(f"/api/consultations/{room}/calls", headers=headers(client)))["items"]
    assert len(rows) == 1 and rows[0]["end_reason"] == reason
    assert (rows[0]["connected_at"] is not None) == (ending == "call_end")
    assert not client.app.state.chat.calls


def test_call_peer_disconnect_and_timeout_are_finalized(client):
    room = active_room(client)
    with client.websocket_connect(f"/ws/chat/{room}?token={token(client)}") as a:
        receive(a, "joined")
        with client.websocket_connect(f"/ws/chat/{room}?token={token(client, 2)}") as b:
            receive(b, "joined")
            a.send_json(
                {"type": "call_offer", "data": {"call_id": "disconnect-call", "sdp": "v=0\r\n"}}
            )
            receive(b, "call_offer")
        assert receive(a, "call_end")["reason"] == "disconnected"
        with client.websocket_connect(f"/ws/chat/{room}?token={token(client, 2)}") as b:
            receive(b, "joined")
            a.send_json(
                {"type": "call_offer", "data": {"call_id": "timeout-call", "sdp": "v=0\r\n"}}
            )
            receive(b, "call_offer")
            client.app.state.chat.calls[str(room)]["deadline"] = 0
            assert receive(a, "call_end")["reason"] == "timeout"
    assert (
        data(client.get(f"/api/consultations/{room}/calls", headers=headers(client)))["total"] == 2
    )
    assert not client.app.state.chat.calls


def test_ended_session_rejects_signaling_and_ends_live_call(client):
    room = active_room(client)
    with client.websocket_connect(f"/ws/chat/{room}?token={token(client)}") as a:
        receive(a, "joined")
        with client.websocket_connect(f"/ws/chat/{room}?token={token(client, 2)}") as b:
            receive(b, "joined")
            a.send_json(
                {"type": "call_offer", "data": {"call_id": "end-session", "sdp": "v=0\r\n"}}
            )
            receive(b, "call_offer")
            data(client.post(f"/api/consultations/{room}/end", headers=headers(client)))
            assert receive(a, "call_end")["reason"] == "consultation_ended"
            a.send_json({"type": "call_offer", "data": {"call_id": "too-late", "sdp": "v=0\r\n"}})
            assert "active" in receive(a, "error")["message"]


def test_signals_preserve_sdp_and_reject_unbounded_input():
    assert Signal(call_id="test", sdp="v=0\r\n").sdp.endswith("\r\n")
    with pytest.raises(ValueError):
        Signal(call_id="test", sdp="x" * 16001)


def test_websocket_query_tokens_are_redacted_from_uvicorn_logs():
    record = logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        "",
        1,
        "WebSocket %s [accepted]",
        ("/ws/chat/1?token=secret-token",),
        None,
    )
    assert RedactWebSocketToken().filter(record)
    assert "secret-token" not in record.getMessage()
    assert "[redacted]" in record.getMessage()


@pytest.mark.parametrize("previous", ["786395e6a0ba", "bd9e76dbea39"])
def test_upgrade_from_each_branch_preserves_data_and_can_downgrade(previous, tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'branch-upgrade.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, previous)
    engine = create_engine(url)
    try:
        with engine.begin() as db:
            db.execute(text("INSERT INTO departments (id, name) VALUES (99, 'Migration sentinel')"))
        command.upgrade(config, "head")
        with engine.connect() as db:
            assert (
                db.scalar(text("SELECT name FROM departments WHERE id=99")) == "Migration sentinel"
            )
            # Read from the script directory, not written down here: a later
            # revision must not be able to make this test lie about where head
            # is. `test_m4_m6_migration.py` does the same for the same reason.
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == (
                ScriptDirectory.from_config(config).get_current_head()
            )
        assert "call_log" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
    command.downgrade(config, "base")
    engine = create_engine(url)
    try:
        assert inspect(engine).get_table_names() == ["alembic_version"]
    finally:
        engine.dispose()


def test_accept_and_answer_have_separate_deadlines_and_cannot_be_replayed(client, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("app.calls.monotonic", lambda: clock[0])
    room = active_room(client)
    with client.websocket_connect(f"/ws/chat/{room}?token={token(client)}") as a:
        receive(a, "joined")
        with client.websocket_connect(f"/ws/chat/{room}?token={token(client, 2)}") as b:
            receive(b, "joined")
            payload = {"call_id": "slow-permission", "sdp": "v=0\r\n"}
            a.send_json({"type": "call_offer", "data": payload})
            receive(b, "call_offer")
            state = client.app.state.chat.calls[str(room)]
            assert state["deadline"] == 1060
            a.send_json({"type": "call_accept", "data": {"call_id": "slow-permission"}})
            receive(a, "error")
            assert state["deadline"] == 1060
            clock[0] = 1059
            b.send_json({"type": "call_accept", "data": {"call_id": "slow-permission"}})
            receive(a, "call_accept")
            assert state["deadline"] == 1104
            b.send_json({"type": "call_accept", "data": {"call_id": "slow-permission"}})
            receive(b, "error")
            assert state["deadline"] == 1104
            clock[0] = 1103
            b.send_json({"type": "call_answer", "data": payload})
            receive(a, "call_answer")
            assert state["deadline"] == 1148
            b.send_json({"type": "call_answer", "data": payload})
            receive(b, "error")
            assert state["deadline"] == 1148
            a.send_json({"type": "call_connected", "data": {"call_id": "slow-permission"}})
            a.send_json({"type": "message", "data": {"content": "timing check"}})
            receive(a, "message")
            assert state["deadline"] is None
            a.send_json({"type": "call_end", "data": {"call_id": "slow-permission"}})
            receive(b, "call_end")


def test_ended_consultation_survives_startup_and_cannot_be_reaccepted(client):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.seed import seed
    from app.seed_demo import seed_demo

    # Match startup order so this test patient does not reuse a demo patient number.
    seed_demo()
    room = active_room(client)
    path = f"/api/consultations/{room}"
    data(client.post(path + "/messages", headers=headers(client), json={"content": "Keep history"}))
    ended = data(client.post(path + "/end", headers=headers(client)))
    assert ended["status"] == "ended" and ended["ended_at"]
    # Repeat the same seeders used by the dev launcher, then create a fresh app.
    seed()
    seed_demo()
    restarted = create_app(client.app.state.settings)
    restarted.state.cache = client.app.state.cache
    with TestClient(restarted) as again:
        restored = data(again.get(path, headers=headers(client)))
        assert restored["status"] == "ended"
        assert restored["ended_at"] == ended["ended_at"]
        listed = data(again.get("/api/consultations?status=ended", headers=headers(client)))
        assert room in {row["id"] for row in listed["items"]}
        messages = data(again.get(path + "/messages", headers=headers(client)))
        assert messages["items"][0]["content"] == "Keep history"
        assert again.post(path + "/accept", headers=headers(client, 2)).status_code == 400
        assert data(again.get(path, headers=headers(client)))["status"] == "ended"
