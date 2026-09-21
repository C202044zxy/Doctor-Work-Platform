"""M3 single-worker WebRTC signaling. Never stores SDP, ICE addresses or media.

Signaling rides the room's own WebSocket, so M5's meetings reuse this module on their
`m<id>` room key. A call connects exactly two participants: a room with more than one
other connection online refuses the offer rather than picking a peer by dictionary
order, because "who am I calling" is not a question the server may answer by accident.
"""

import asyncio
from datetime import UTC, datetime
from time import monotonic

from fastapi import HTTPException
from pydantic import ConfigDict, Field
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app import rooms
from app.audit import persist_audit
from app.work_models import CallLog
from app.work_schemas import Input

RING_TIMEOUT_SECONDS = 60
CONNECT_TIMEOUT_SECONDS = 45


class Signal(Input):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    call_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9-]+$")
    sdp: str | None = Field(default=None, max_length=16000)
    candidate: dict | None = None


def save_finished(app, state, reason):
    ended = datetime.now(UTC)
    connected = state.get("connected_at")
    key = state["room"]
    kind, _ = rooms.parse(key)
    with app.state.chat.write_lock, app.state.sessions() as db:
        row = db.scalar(select(CallLog).where(CallLog.call_id == state["call_id"]))
        if row is None:
            row = CallLog(
                room_key=key,
                consultation_id=rooms.consultation_id_of(key),
                call_id=state["call_id"],
                started_at=state["started_at"],
                connected_at=connected,
                ended_at=ended,
                duration_seconds=max(0, int((ended - connected).total_seconds()))
                if connected
                else 0,
                end_reason=reason,
            )
            db.add(row)
            db.commit()
        row_id = row.id
    persist_audit(
        app.state.sessions,
        {
            "action": "meeting.call.end" if kind == rooms.MEETING else "consultation.call.end",
            "object_type": "call_log",
            "object_id": str(row_id),
            "user_id": state["caller_user"],
            "result": "success",
            "status_code": 200,
            "detail": {"reason": reason},
        },
    )


def send(hub, key, kind, data):
    client = hub.clients.get(key)
    if client:
        queue = client[2]
        if not queue.full():
            queue.put_nowait({"type": kind, "data": data})


async def finish(app, room, reason):
    state = app.state.chat.calls.pop(room, None)
    if state is None:
        return
    # Finish is idempotent on the event loop; persist before informing either peer.
    await run_in_threadpool(save_finished, app, state, reason)
    for key in (state["caller"], state["callee"]):
        send(app.state.chat, key, "call_end", {"call_id": state["call_id"], "reason": reason})


async def handle(app, room, user, connection, kind, payload):
    body = Signal.model_validate(payload)
    hub = app.state.chat
    with app.state.sessions() as db:
        db.info["user"] = user
        session = rooms.room(db, room, participant=True)
        if not session.writable:
            raise HTTPException(
                409, f"Video calls require the {session.label} to be {session.ready}"
            )
        if kind == "call_offer" and db.scalar(
            select(CallLog.id).where(CallLog.call_id == body.call_id)
        ):
            raise HTTPException(409, "Call identifier already used")
    state = hub.calls.get(room)
    if kind == "call_offer":
        if any(call["call_id"] == body.call_id for call in hub.calls.values()):
            raise HTTPException(409, "Call identifier already used")
        if state:
            raise HTTPException(409, "A call is already in progress")
        if not body.sdp:
            raise HTTPException(422, "Offer SDP is required")
        peers = [
            key for key, (rid, uid, _) in hub.clients.items() if rid == room and uid != user.id
        ]
        if not peers:
            raise HTTPException(409, "The other participant is offline; ask them to open this room")
        if len(peers) > 1:
            # The offer carries no addressee and a call connects two peers, so with
            # three or more connections there is no honest way to choose one. Refusing
            # beats silently picking a participant for the caller.
            raise HTTPException(
                409,
                "A video call connects two participants, and "
                f"{len(peers)} others are online in this room; ask the rest to leave first",
            )
        peer = peers[0]
        state = {
            "room": room,
            "call_id": body.call_id,
            "caller": connection,
            "callee": peer,
            "caller_user": user.id,
            "started_at": datetime.now(UTC),
            "connected_at": None,
            "deadline": monotonic() + RING_TIMEOUT_SECONDS,
            "accepted": False,
            "answered": False,
        }
        hub.calls[room] = state
        send(hub, peer, kind, {"call_id": body.call_id, "sdp": body.sdp, "sender_name": user.name})
        return
    if (
        not state
        or state["call_id"] != body.call_id
        or connection not in (state["caller"], state["callee"])
    ):
        raise HTTPException(409, "Call is no longer available on this connection")
    peer = state["callee"] if connection == state["caller"] else state["caller"]
    if kind == "call_accept":
        if connection != state["callee"] or state["accepted"] or state["answered"]:
            raise HTTPException(409, "Only the invited connection may accept once")
        state["accepted"] = True
        state["deadline"] = monotonic() + CONNECT_TIMEOUT_SECONDS
        send(hub, peer, kind, {"call_id": body.call_id})
    elif kind == "call_answer":
        if connection != state["callee"] or state["answered"] or not body.sdp:
            raise HTTPException(409, "Only the invited connection may answer once")
        state["accepted"] = True
        state["answered"] = True
        state["deadline"] = monotonic() + CONNECT_TIMEOUT_SECONDS
        send(hub, peer, kind, {"call_id": body.call_id, "sdp": body.sdp})
    elif kind == "ice_candidate":
        send(hub, peer, kind, {"call_id": body.call_id, "candidate": body.candidate})
    elif kind == "call_connected":
        if not state["answered"]:
            raise HTTPException(409, "Call has not been answered")
        if state["connected_at"] is None:
            state["connected_at"] = datetime.now(UTC)
            state["deadline"] = None
    elif kind in {"call_end", "call_reject"}:
        await finish(app, room, "rejected" if kind == "call_reject" else "hangup")
    else:
        raise HTTPException(422, "Unknown call event")


async def disconnected(app, connection):
    for room, state in list(app.state.chat.calls.items()):
        if connection in (state["caller"], state["callee"]):
            await finish(app, room, "disconnected")


async def sweep(app):
    while True:
        await asyncio.sleep(1)
        for room, state in list(app.state.chat.calls.items()):
            if state["deadline"] is not None and monotonic() >= state["deadline"]:
                await finish(app, room, "timeout")
