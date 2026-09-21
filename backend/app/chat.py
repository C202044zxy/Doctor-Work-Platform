"""M3 chat: single worker, durable history and bounded live queues.

One socket serves both kinds of conversation, so M5's remote consultation reuses this
module rather than opening a second chat of its own. The room key is the spelling
`app.rooms` defines: digits for a patient consultation, `m<id>` for a meeting.
"""

import asyncio
import contextlib
import io
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Annotated, Literal

import anyio
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.encoders import jsonable_encoder
from fastapi.security import HTTPAuthorizationCredentials
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError
from redis.exceptions import RedisError
from sqlalchemy import select, update
from starlette.concurrency import run_in_threadpool
from starlette.staticfiles import StaticFiles

from app import calls, rooms
from app.audit import mark_audit, persist_audit
from app.auth import current_user
from app.dependencies import Pagination
from app.models import Patient, User
from app.patients import visible_patient
from app.security import allows, require_permission
from app.work_common import DB, call_data, fields, ok, page
from app.work_models import CallLog, Consultation, ConsultMessage, ImageUpload
from app.work_schemas import (
    CallRead,
    ConsultationCreate,
    Envelope,
    MessageCreate,
    MessageRead,
    PageData,
    RoomRead,
    UploadRead,
)

router = APIRouter(
    tags=["Consultations"], dependencies=[Depends(require_permission("consult.write"))]
)
socket_router = APIRouter()
# M5's room: the same machinery on an `m<id>` key. The paths are M5's because their
# subject is a meeting, but the code is this one chat implementation, deliberately not
# a second one -- `docs/api/API-索引.md` requires consultations and meetings to share
# the route rather than each opening their own.
meeting_router = APIRouter(
    tags=["Meetings"], dependencies=[Depends(require_permission("consult.write"))]
)
Paging = Annotated[Pagination, Depends()]


class ChatHub:
    def __init__(self):
        self.rooms = {}
        self.clients = {}
        self.calls = {}
        self.write_lock = RLock()

    def subscribe(self, room):
        queue = asyncio.Queue(maxsize=256)
        self.rooms.setdefault(room, set()).add(queue)
        return queue

    def unsubscribe(self, room, queue):
        self.rooms.get(room, set()).discard(queue)
        if not self.rooms.get(room):
            self.rooms.pop(room, None)

    async def publish(self, room, event):
        encoded = jsonable_encoder(event)
        for queue in tuple(self.rooms.get(room, ())):
            if queue.full():
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait({"type": "overflow", "data": {}})
            else:
                queue.put_nowait(encoded)


def room_data(db, row):
    doctor = db.get(User, row.doctor_id) if row.doctor_id else None
    patient = db.get(Patient, row.patient_id)
    return {
        **fields(
            row,
            "id",
            "doctor_id",
            "status",
            "last_message",
            "last_message_at",
            "started_at",
            "ended_at",
            "created_at",
        ),
        "patient_no": patient.patient_no,
        "patient_name": patient.name,
        "doctor_name": doctor.name if doctor else None,
        "is_participant": db.info["user"].id in (row.created_by, row.doctor_id),
    }


def message_data(row):
    return fields(
        row,
        "id",
        "room_key",
        "consultation_id",
        "sender_type",
        "sender_name",
        "content",
        "image_url",
        "sent_at",
        "client_id",
    )


@router.get("/api/consultations", response_model=Envelope[PageData[RoomRead]])
def list_rooms(
    db: DB,
    pagination: Paging,
    status: Literal["waiting", "active", "ended"] | None = None,
    patient_no: str | None = None,
):
    stmt = rooms.consultation_scope(db)
    if status:
        stmt = stmt.where(Consultation.status == status)
    if patient_no:
        stmt = stmt.where(Patient.patient_no == patient_no)
    return ok(
        page(
            db,
            stmt.order_by(Consultation.last_message_at.desc(), Consultation.id.desc()),
            pagination,
            lambda row: room_data(db, row),
        )
    )


@router.post("/api/consultations", response_model=Envelope[RoomRead])
def create_room(body: ConsultationCreate, db: DB):
    patient = visible_patient(db, db.info["user"], body.patient_no)
    row = Consultation(patient_id=patient.id, created_by=db.info["user"].id)
    db.add(row)
    db.flush()
    mark_audit(
        db.info["request"], "consultation.create", "consultation", row.id, patient_id=patient.id
    )
    db.commit()
    return ok(room_data(db, row))


@router.get("/api/consultations/{id}", response_model=Envelope[RoomRead])
def read_room(id: int, db: DB):
    room = rooms.consultation_room(db, id)
    mark_audit(
        db.info["request"],
        "consultation.view",
        "consultation",
        id,
        patient_id=room.patient_id,
    )
    return ok(room_data(db, room.row))


def transition(app, user, room_id, target):
    with app.state.chat.write_lock, app.state.sessions() as db:
        db.info["user"] = user
        row = rooms.consultation_room(db, room_id, participant=target == "ended").row
        expected = "waiting" if target == "active" else "active"
        if row.status != expected:
            raise HTTPException(400, f"Consultation must be {expected}")
        changes = {"status": target}
        if target == "active":
            changes.update(doctor_id=user.id, started_at=datetime.now(UTC))
        else:
            changes["ended_at"] = datetime.now(UTC)
        changed = db.execute(
            update(Consultation)
            .where(Consultation.id == room_id, Consultation.status == expected)
            .values(**changes)
        )
        if changed.rowcount != 1:
            raise HTTPException(409, "Consultation changed; reload and retry")
        db.commit()
        db.refresh(row)
        return room_data(db, row)


async def change_room(db, id, target):
    request = db.info["request"]
    result = await run_in_threadpool(transition, request.app, db.info["user"], id, target)
    if target == "ended":
        await calls.finish(request.app, rooms.consultation_key(id), "consultation_ended")
    mark_audit(
        request,
        "consultation.accept" if target == "active" else "consultation.end",
        "consultation",
        id,
    )
    await request.app.state.chat.publish(
        rooms.consultation_key(id), {"type": "status", "data": result}
    )
    return ok(result)


@router.post("/api/consultations/{id}/accept", response_model=Envelope[RoomRead])
async def accept_room(id: int, db: DB):
    return await change_room(db, id, "active")


@router.post("/api/consultations/{id}/end", response_model=Envelope[RoomRead])
async def end_room(id: int, db: DB):
    return await change_room(db, id, "ended")


def room_history(db, room, pagination, before_id, after_id):
    """The one history reader: cursor paging on the room, not on the room's kind."""
    if before_id is not None and after_id is not None:
        raise HTTPException(422, "Use before_id or after_id, not both")
    stmt = select(ConsultMessage).where(ConsultMessage.room_key == room.key)
    if before_id is not None:
        stmt = stmt.where(ConsultMessage.id < before_id)
    if after_id is not None:
        stmt = stmt.where(ConsultMessage.id > after_id)
    return ok(
        page(
            db,
            stmt.order_by(
                ConsultMessage.id.asc() if after_id is not None else ConsultMessage.id.desc()
            ),
            pagination,
            message_data,
        )
    )


@router.get("/api/consultations/{id}/messages", response_model=Envelope[PageData[MessageRead]])
def history(
    id: int,
    db: DB,
    pagination: Paging,
    before_id: int | None = Query(None, gt=0),
    after_id: int | None = Query(None, ge=0),
):
    room = rooms.consultation_room(db, id)
    mark_audit(
        db.info["request"],
        "consultation.messages.view",
        "consultation",
        id,
        patient_id=room.patient_id,
    )
    return room_history(db, room, pagination, before_id, after_id)


@meeting_router.get("/api/meetings/{id}/messages", response_model=Envelope[PageData[MessageRead]])
def meeting_history(
    id: int,
    db: DB,
    pagination: Paging,
    before_id: int | None = Query(None, gt=0),
    after_id: int | None = Query(None, ge=0),
):
    """会诊聊天室历史 / The meeting room's history, read by the same cursor rules.

    Participants only, and the same `before_id`/`after_id` cursors as the patient
    consultation: M5's room is this module's chat on another room key, which is what
    `docs/api/API-索引.md` asks for instead of a second chat implementation.
    """
    room = rooms.meeting_room(db, id, participant=True)
    mark_audit(
        db.info["request"], "meeting.messages.view", "meeting", id, patient_id=room.patient_id
    )
    return room_history(db, room, pagination, before_id, after_id)


def store_message(app, user, key, body):
    """Persist one message in either kind of room and hand back its stored id."""
    with app.state.chat.write_lock, app.state.sessions() as db:
        db.info["user"] = user
        room = rooms.room(db, key, participant=True)
        if body.client_id:
            previous = db.scalar(
                select(ConsultMessage).where(
                    ConsultMessage.room_key == room.key,
                    ConsultMessage.sender_id == user.id,
                    ConsultMessage.client_id == body.client_id,
                )
            )
            if previous:
                if (previous.content, previous.image_url) != (body.content, body.image_url):
                    raise HTTPException(409, "client_id was used for a different message")
                return message_data(previous)
        if not room.writable:
            raise HTTPException(
                409, f"Messages are only accepted while the {room.label} is {room.ready}"
            )
        if body.image_url:
            filename = body.image_url.removeprefix("/uploads/")
            if body.image_url != f"/uploads/{Path(filename).name}":
                raise HTTPException(422, "Invalid image_url")
            upload = db.scalar(
                select(ImageUpload).where(
                    ImageUpload.filename == filename, ImageUpload.owner_id == user.id
                )
            )
            if (
                upload is None
                or upload.room_key not in (None, room.key)
                or not (Path(app.state.settings.upload_dir) / filename).is_file()
            ):
                raise HTTPException(422, "Upload your image before sending it")
            upload.room_key = room.key
        row = ConsultMessage(
            room_key=room.key,
            consultation_id=rooms.consultation_id_of(room.key),
            sender_id=user.id,
            sender_type=room.sender_type_for(user),
            sender_name=user.name,
            **body.model_dump(),
        )
        db.add(row)
        db.flush()
        # Only a consultation carries a list preview; a meeting has no queue to show one in.
        if room.kind == rooms.CONSULTATION:
            consultation = db.get(Consultation, room.id)
            consultation.last_message = (body.content or "[Image]")[:200]
            consultation.last_message_at = row.sent_at
        db.commit()
        result = message_data(row)
    persist_audit(
        app.state.sessions,
        {
            "action": "meeting.message" if room.kind == rooms.MEETING else "consultation.message",
            "object_type": "consult_message",
            "object_id": str(result["id"]),
            "patient_id": room.patient_id,
            "user_id": user.id,
            "result": "success",
            "status_code": 200,
        },
    )
    return result


@router.post("/api/consultations/{id}/messages", response_model=Envelope[MessageRead])
async def send_message(id: int, body: MessageCreate, db: DB):
    app = db.info["request"].app
    key = rooms.consultation_key(id)
    data = await run_in_threadpool(store_message, app, db.info["user"], key, body)
    await app.state.chat.publish(key, {"type": "message", "data": data})
    return ok(data)


@meeting_router.post("/api/meetings/{id}/messages", response_model=Envelope[MessageRead])
async def send_meeting_message(id: int, body: MessageCreate, db: DB):
    """会诊聊天室 HTTP 兜底 / The meeting room's HTTP fallback, exactly as M3's.

    The socket is the normal path; this exists for the same reason the consultation one
    does, so a client whose socket is down can still send, and it is the same
    `store_message` either way.
    """
    app = db.info["request"].app
    key = rooms.meeting_key(id)
    data = await run_in_threadpool(store_message, app, db.info["user"], key, body)
    await app.state.chat.publish(key, {"type": "message", "data": data})
    return ok(data)


@meeting_router.get("/api/meetings/{id}/calls", response_model=Envelope[PageData[CallRead]])
def meeting_calls(id: int, db: DB, pagination: Paging):
    """会诊通话记录 / Finished calls in the meeting room.

    Read through the same `CallRead` renderer as M3's call history: a call is a call
    whichever kind of room it happened in.
    """
    room = rooms.meeting_room(db, id, participant=True)
    return ok(
        page(
            db,
            select(CallLog).where(CallLog.room_key == room.key).order_by(CallLog.id.desc()),
            pagination,
            call_data,
        )
    )


def checked_image(content):
    try:
        with Image.open(io.BytesIO(content)) as image:
            fmt = image.format
            if fmt not in {"JPEG", "PNG", "WEBP"} or image.width * image.height > 25_000_000:
                raise ValueError()
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            image.load()
            output = io.BytesIO()
            image.save(output, format=fmt)
        return output.getvalue(), {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}[fmt]
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(422, "File must contain a valid JPEG, PNG or WebP image") from None


@router.post("/api/uploads/images", response_model=Envelope[UploadRead])
async def upload_image(db: DB, file: Annotated[UploadFile, File()]):
    content = await file.read(5 * 1024 * 1024 + 1)
    await file.close()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(413, "Image exceeds the 5MB limit")
    content, extension = await run_in_threadpool(checked_image, content)
    filename = f"{uuid.uuid4().hex}.{extension}"
    root = Path(db.info["request"].app.state.settings.upload_dir)
    root.mkdir(parents=True, exist_ok=True)
    target = root / filename
    try:
        await run_in_threadpool(target.write_bytes, content)
        db.add(ImageUpload(filename=filename, owner_id=db.info["user"].id))
        db.commit()
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return ok({"url": f"/uploads/{filename}"})


@router.get("/uploads/{filename}")
async def read_image(filename: str, db: DB):
    row = db.scalar(select(ImageUpload).where(ImageUpload.filename == filename))
    if row is None:
        raise HTTPException(404, "Image not found")
    if row.room_key:
        rooms.room(db, row.room_key)
    elif row.owner_id != db.info["user"].id:
        raise HTTPException(404, "Image not found")
    request = db.info["request"]
    mark_audit(request, "consultation.image.view", "image_upload", row.id)
    response = await StaticFiles(
        directory=request.app.state.settings.upload_dir, check_dir=False
    ).get_response(filename, request.scope)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def socket_identity(ws, token, room_id):
    user = current_user(
        ws, HTTPAuthorizationCredentials(scheme="Bearer", credentials=token) if token else None
    )
    if not allows(user, "consult.write"):
        raise HTTPException(403, "Missing consult.write permission")
    with ws.app.state.sessions() as db:
        db.info["user"] = user
        # One scoped join instead of loading the room, patient, and patient again
        # for every outbound frame. Authorization still runs on every event.
        rooms.room(db, room_id, participant=True)
    return user


@socket_router.websocket("/ws/chat/{room_id}")
async def chat_socket(ws: WebSocket, room_id: str, token: str = ""):
    """The one room socket. `room_id` is a room key rather than a consultation id:
    bare digits name a consultation and `m<id>` names a meeting, which is why it is a
    string here and why both kinds reach the same handlers below."""
    try:
        user = await run_in_threadpool(socket_identity, ws, token, room_id)
    except (HTTPException, RedisError):
        await ws.close(code=1008)
        return
    hub, cache = ws.app.state.chat, ws.app.state.cache
    key = f"chat:presence:{room_id}:{user.id}:{uuid.uuid4().hex}"
    queue = hub.subscribe(room_id)
    await ws.accept()
    hub.clients[key] = (room_id, user.id, queue)
    last_received = monotonic()

    async def writer():
        lease_refreshed = monotonic()
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), 5)
            except TimeoutError:
                event = {"type": "ping", "data": {}}
            if monotonic() - last_received > 20:
                await ws.close(code=1001)
                return
            await run_in_threadpool(socket_identity, ws, token, room_id)
            # Presence expires after 60s and is renewed every 20s, independent
            # of traffic volume. Avoid a redundant Redis write per message.
            if monotonic() - lease_refreshed >= 20:
                await run_in_threadpool(cache.set, key, "1", ex=60)
                lease_refreshed = monotonic()
            if event["type"] == "overflow":
                await ws.close(code=1013)
                return
            await ws.send_json(event)
            if event["type"] != "ping" and monotonic() - last_received > 5:
                await ws.send_json({"type": "ping", "data": {}})

    async def reader():
        nonlocal last_received
        while True:
            raw = await ws.receive_text()
            last_received = monotonic()
            if len(raw) > 20000:
                await ws.close(code=1009)
                return
            event = None
            try:
                event = json.loads(raw)
                if not isinstance(event, dict):
                    raise TypeError()
                identity = await run_in_threadpool(socket_identity, ws, token, room_id)
                if event.get("type") == "pong":
                    continue
                if event.get("type") == "message":
                    body = MessageCreate.model_validate(event.get("data"))
                    data = await run_in_threadpool(store_message, ws.app, identity, room_id, body)
                    await hub.publish(room_id, {"type": "message", "data": data})
                elif event.get("type") == "typing":
                    await hub.publish(room_id, {"type": "typing", "data": {"user_id": identity.id}})
                elif event.get("type") in {
                    "call_offer",
                    "call_accept",
                    "call_answer",
                    "ice_candidate",
                    "call_connected",
                    "call_reject",
                    "call_end",
                }:
                    await calls.handle(
                        ws.app, room_id, identity, key, event["type"], event.get("data")
                    )
                else:
                    raise ValueError()
            except (ValidationError, ValueError, TypeError, HTTPException) as exc:
                await queue.put(
                    {
                        "type": "error",
                        "data": {
                            "message": exc.detail
                            if isinstance(exc, HTTPException)
                            else "Invalid chat event",
                            "event_type": event.get("type") if isinstance(event, dict) else None,
                            "call_id": event.get("data", {}).get("call_id")
                            if isinstance(event, dict) and isinstance(event.get("data"), dict)
                            else None,
                            "client_id": event.get("data", {}).get("client_id")
                            if isinstance(event, dict) and isinstance(event.get("data"), dict)
                            else None,
                        },
                    }
                )

    tasks = []
    try:
        await run_in_threadpool(cache.set, key, "1", ex=60)
        await hub.publish(room_id, {"type": "joined", "data": {"user_id": user.id}})
        tasks = [asyncio.create_task(writer()), asyncio.create_task(reader())]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except (WebSocketDisconnect, HTTPException, RedisError, RuntimeError, asyncio.CancelledError):
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await ws.close(code=1008)
    finally:
        # ASGI disconnect cancels the connection scope. Shield cleanup so Redis
        # leases are removed immediately even when the client vanishes mid-send.
        with anyio.CancelScope(shield=True):
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            hub.unsubscribe(room_id, queue)
            hub.clients.pop(key, None)
            await calls.disconnected(ws.app, key)
            with contextlib.suppress(RedisError):
                await run_in_threadpool(cache.delete, key)
            await hub.publish(room_id, {"type": "left", "data": {"user_id": user.id}})
