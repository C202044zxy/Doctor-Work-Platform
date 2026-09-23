"""Participant-only, ordered WebM uploads with durable chunks and protected playback."""

import hashlib
import shutil
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi import Path as PathParam
from fastapi.responses import FileResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app import rooms
from app.audit import mark_audit
from app.auth import CurrentUser, ok
from app.models import User
from app.work_models import CallRecording

router = APIRouter(tags=["Recordings"])
MAX_CHUNK = 8 * 1024 * 1024
MAX_RECORDING = 256 * 1024 * 1024
CALL_PATH = "/api/rooms/{room_key}/calls/{call_id}/recordings"
RECORDING_PATH = "/api/recordings/{recording_id}"
TEST_PATH = "/api/rooms/{room_key}/test-recordings"


def filename_for(created_at):
    stamp = created_at.astimezone(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S_%f")
    return f"Test_{stamp}.webm"


def folder(request, row):
    # The path uses only a server-generated UUID, never an upload filename or room key.
    return Path(request.app.state.settings.upload_dir).resolve() / "recordings" / row.id


def authorize(db, user, key):
    db.info["user"] = user
    resolved = rooms.room(db, key, participant=True)
    if resolved.key != key:
        raise HTTPException(404, "Room not found")
    return resolved


def recording(db, user, recording_id, *, owner=False):
    row = db.get(CallRecording, recording_id)
    if row is None:
        raise HTTPException(404, "Recording not found")
    authorize(db, user, row.room_key)
    if owner and row.owner_id != user.id:
        raise HTTPException(403, "Only the recording owner may upload or finalize")
    return row


def summary(request, db, row):
    state = request.app.state.chat.calls.get(row.room_key)
    live = state is not None and state["call_id"] == row.call_id
    status = row.status if row.status == "ready" or live else "partial"
    owner = db.get(User, row.owner_id)
    return {
        "id": row.id,
        "call_id": row.call_id,
        "owner_name": owner.name,
        "status": status,
        "byte_size": row.byte_size,
        "next_sequence": row.next_sequence,
        "playable": row.byte_size > 0 and (row.status == "ready" or not live),
        "is_test": row.is_test,
        "filename": row.filename or "replay.webm",
    }


@router.post(TEST_PATH + "/{test_id}")
def start_test_recording(request: Request, user: CurrentUser, room_key: str, test_id: UUID):
    with request.app.state.chat.write_lock, request.app.state.sessions() as db:
        resolved = authorize(db, user, room_key)
        call_id = f"test-{test_id}"
        existing = db.scalar(
            select(CallRecording).where(
                CallRecording.call_id == call_id, CallRecording.owner_id == user.id
            )
        )
        if existing is not None:
            if existing.room_key != room_key or not existing.is_test:
                raise HTTPException(404, "Recording not found")
            return ok(summary(request, db, existing))
        if not resolved.writable:
            raise HTTPException(409, "The room must be active to record a test")
        created_at = datetime.now(UTC)
        row = CallRecording(
            id=uuid4().hex,
            room_key=room_key,
            call_id=call_id,
            owner_id=user.id,
            is_test=True,
            filename=filename_for(created_at),
            created_at=created_at,
        )
        db.add(row)
        db.commit()
        mark_audit(request, "call.recording.start", "call_recording", row.id)
        return ok(summary(request, db, row))


@router.get(TEST_PATH)
def list_test_recordings(request: Request, user: CurrentUser, room_key: str):
    with request.app.state.sessions() as db:
        authorize(db, user, room_key)
        rows = db.scalars(
            select(CallRecording)
            .where(CallRecording.room_key == room_key, CallRecording.is_test.is_(True))
            .order_by(CallRecording.created_at.desc())
            .limit(100)
        )
        return ok([summary(request, db, row) for row in rows])


@router.post(CALL_PATH)
def start_recording(request: Request, user: CurrentUser, room_key: str, call_id: str):
    with request.app.state.chat.write_lock, request.app.state.sessions() as db:
        authorize(db, user, room_key)
        existing = db.scalar(
            select(CallRecording).where(
                CallRecording.call_id == call_id, CallRecording.owner_id == user.id
            )
        )
        if existing is not None:
            if existing.room_key != room_key:
                raise HTTPException(404, "Recording not found")
            return ok(summary(request, db, existing))
        state = request.app.state.chat.calls.get(room_key)
        if (
            not state
            or state["call_id"] != call_id
            or not state["connected_at"]
            or user.id not in (state["caller_user"], state["callee_user"])
        ):
            raise HTTPException(409, "Only connected call participants can start a recording")
        row = CallRecording(id=uuid4().hex, room_key=room_key, call_id=call_id, owner_id=user.id)
        db.add(row)
        db.commit()
        mark_audit(request, "call.recording.start", "call_recording", row.id)
        return ok(summary(request, db, row))


@router.get(CALL_PATH)
def list_recordings(request: Request, user: CurrentUser, room_key: str, call_id: str):
    with request.app.state.sessions() as db:
        authorize(db, user, room_key)
        rows = db.scalars(
            select(CallRecording)
            .where(CallRecording.room_key == room_key, CallRecording.call_id == call_id)
            .order_by(CallRecording.created_at)
        )
        return ok([summary(request, db, row) for row in rows])


def save_chunk(request, user, recording_id, sequence, content):
    with request.app.state.chat.write_lock, request.app.state.sessions() as db:
        row = recording(db, user, recording_id, owner=True)
        directory = folder(request, row)
        path = directory / f"{sequence:06d}.chunk"
        if sequence < row.next_sequence:
            if (
                not path.exists()
                or hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(content).digest()
            ):
                raise HTTPException(409, "Chunk retry differs from the saved bytes")
            return ok(summary(request, db, row))
        if row.status == "ready" or sequence != row.next_sequence:
            raise HTTPException(409, "Recording is finalized or chunk is out of order")
        if not content or (sequence == 0 and not content.startswith(b"\x1aE\xdf\xa3")):
            raise HTTPException(422, "A nonempty WebM recording is required")
        if row.byte_size + len(content) > MAX_RECORDING:
            raise HTTPException(413, "Recording exceeds the 256MB limit")
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / "chunk.tmp"
        temporary.write_bytes(content)
        temporary.replace(path)
        row.byte_size += len(content)
        row.next_sequence += 1
        db.commit()
        return ok(summary(request, db, row))


@router.put(RECORDING_PATH + "/chunks/{sequence}")
async def upload_chunk(
    request: Request,
    user: CurrentUser,
    recording_id: str,
    sequence: int = PathParam(ge=0, le=100000),
):
    # Authorize before accepting any upload body; also check again under the write lock.
    with request.app.state.sessions() as db:
        recording(db, user, recording_id, owner=True)
    if request.headers.get("content-type", "").split(";")[0] != "video/webm":
        raise HTTPException(415, "Content-Type must be video/webm")
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_CHUNK:
            raise HTTPException(413, "Recording chunk exceeds the 8MB limit")
    return await run_in_threadpool(
        save_chunk, request, user, recording_id, sequence, bytes(content)
    )


def assemble(request, row):
    directory = folder(request, row)
    output = directory / (row.filename or "replay.webm")
    if output.exists() and output.stat().st_size == row.byte_size:
        return output
    temporary = directory / "replay.tmp"
    try:
        with temporary.open("wb") as destination:
            for index in range(row.next_sequence):
                with (directory / f"{index:06d}.chunk").open("rb") as source:
                    shutil.copyfileobj(source, destination)
        temporary.replace(output)
    except OSError:
        raise HTTPException(503, "Recording storage is unavailable") from None
    return output


@router.post(RECORDING_PATH + "/complete")
def complete(request: Request, user: CurrentUser, recording_id: str):
    with request.app.state.chat.write_lock, request.app.state.sessions() as db:
        row = recording(db, user, recording_id, owner=True)
        if not row.byte_size:
            raise HTTPException(409, "No recording chunks have arrived")
        assemble(request, row)
        row.status = "ready"
        db.commit()
        mark_audit(request, "call.recording.complete", "call_recording", row.id)
        return ok(summary(request, db, row))


@router.get(RECORDING_PATH + "/media")
def playback(request: Request, user: CurrentUser, recording_id: str):
    with request.app.state.chat.write_lock, request.app.state.sessions() as db:
        row = recording(db, user, recording_id)
        if not summary(request, db, row)["playable"]:
            raise HTTPException(409, "Recording is still in progress or contains no media")
        path = assemble(request, row)
        return FileResponse(
            path,
            media_type="video/webm",
            filename=row.filename or "replay.webm",
            content_disposition_type="inline",
            headers={"Cache-Control": "private, no-store"},
        )
