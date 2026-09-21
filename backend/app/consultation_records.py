"""M3 record search, filtered CSV, and finished call history."""

import csv
import io
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import exists, or_, select

from app.audit import mark_audit
from app.audit_export import content_disposition
from app.chat import Paging, room_data
from app.models import Patient
from app.rooms import consultation_key, consultation_room, consultation_scope
from app.security import require_permission
from app.work_common import DB, call_data, ok, page, utc
from app.work_models import CallLog, Consultation, ConsultMessage
from app.work_schemas import CallRead, Envelope, Input, PageData, RoomRead

router = APIRouter(
    tags=["Consultations"], dependencies=[Depends(require_permission("consult.write"))]
)


class RecordFilters:
    def __init__(
        self,
        patient_no: str = "",
        patient: Annotated[str, Query(max_length=100)] = "",
        q: Annotated[str, Query(max_length=200)] = "",
        from_: Annotated[date | None, Query(alias="from")] = None,
        to: date | None = None,
    ):
        if from_ and to and from_ > to:
            raise HTTPException(422, "from must not be after to")
        self.patient_no, self.patient, self.q = patient_no.strip(), patient.strip(), q.strip()
        self.start, self.end = from_, to

    def statement(self, db):
        stmt = consultation_scope(db)
        if self.patient_no:
            stmt = stmt.where(Patient.patient_no == self.patient_no)
        if self.patient:
            stmt = stmt.where(
                or_(
                    Patient.name.contains(self.patient, autoescape=True),
                    Patient.patient_no == self.patient,
                )
            )
        if self.q:
            stmt = stmt.where(
                exists(
                    select(ConsultMessage.id).where(
                        ConsultMessage.consultation_id == Consultation.id,
                        ConsultMessage.content.contains(self.q, autoescape=True),
                    )
                )
            )
        zone = ZoneInfo("Asia/Shanghai")
        if self.start:
            start = datetime.combine(self.start, time.min, zone).astimezone(UTC)
            stmt = stmt.where(Consultation.created_at >= start)
        if self.end:
            # Avoid overflowing date.max on malformed inputs.
            if self.end == date.max:
                raise HTTPException(422, "to is outside the supported date range")
            end = datetime.combine(self.end + timedelta(days=1), time.min, zone).astimezone(UTC)
            stmt = stmt.where(Consultation.created_at < end)
        return stmt.order_by(Consultation.created_at.desc(), Consultation.id.desc())


Filters = Annotated[RecordFilters, Depends()]


@router.get("/api/consultations/records", response_model=Envelope[PageData[RoomRead]])
def records(db: DB, pagination: Paging, filters: Filters):
    mark_audit(db.info["request"], "consultation.records.search", "consultation")
    return ok(page(db, filters.statement(db), pagination, lambda row: room_data(db, row)))


@router.get("/api/consultations/export")
def export_records(db: DB, filters: Filters):
    columns = (
        "id",
        "patient_no",
        "patient_name",
        "doctor_name",
        "status",
        "created_at",
        "started_at",
        "ended_at",
        "last_message",
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    for row in db.scalars(filters.statement(db)):
        data = room_data(db, row)
        values = []
        for column in columns:
            value = data.get(column)
            value = value.isoformat() if isinstance(value, datetime) else str(value or "")
            # Neutralize spreadsheet formulas in untrusted names and message text.
            if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
                value = "'" + value
            values.append(value)
        writer.writerow(values)
    mark_audit(db.info["request"], "consultation.records.export", "consultation")
    filename = f"consultations-{filters.start or 'all'}_{filters.end or 'all'}.csv"
    return Response(
        "\ufeff" + output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": content_disposition(filename),
            "Cache-Control": "no-store",
        },
    )


class CallCreate(Input):
    call_id: str | None = Field(default=None, min_length=1, max_length=64)
    started_at: AwareDatetime
    connected_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None
    duration_seconds: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def chronological(self):
        self.ended_at = self.ended_at or datetime.now(UTC)
        if self.started_at > self.ended_at or self.ended_at > datetime.now(UTC) + timedelta(
            seconds=5
        ):
            raise ValueError("Invalid call time range")
        if self.connected_at and not self.started_at <= self.connected_at <= self.ended_at:
            raise ValueError("connected_at must be within the call")
        duration = (
            int((self.ended_at - self.connected_at).total_seconds()) if self.connected_at else 0
        )
        if self.duration_seconds is not None and self.duration_seconds != duration:
            raise ValueError("duration_seconds must match the connected interval")
        self.duration_seconds = duration
        return self


@router.get("/api/consultations/{id}/calls", response_model=Envelope[PageData[CallRead]])
def calls(id: int, db: DB, pagination: Paging):
    consultation_room(db, id)
    return ok(
        page(
            db,
            select(CallLog)
            .where(CallLog.room_key == consultation_key(id))
            .order_by(CallLog.id.desc()),
            pagination,
            call_data,
        )
    )


@router.post("/api/consultations/{id}/calls", response_model=Envelope[CallRead])
def record_call(id: int, body: CallCreate, db: DB):
    consultation_room(db, id, participant=True)
    call_id = body.call_id or uuid.uuid4().hex
    if any(
        state["call_id"] == call_id for state in db.info["request"].app.state.chat.calls.values()
    ):
        raise HTTPException(409, "Live calls are recorded by the signaling server when they end")
    with db.info["request"].app.state.chat.write_lock:
        existing = db.scalar(select(CallLog).where(CallLog.call_id == call_id))
        if existing:
            if existing.room_key != consultation_key(id):
                raise HTTPException(409, "Call identifier already used")
            if any(
                utc(getattr(existing, key)) != value
                for key, value in body.model_dump().items()
                if key not in {"call_id", "duration_seconds"}
            ):
                raise HTTPException(409, "Call retry differs from the saved record")
            return ok(call_data(existing))
        row = CallLog(
            room_key=consultation_key(id),
            consultation_id=id,
            **body.model_dump(exclude={"call_id"}),
            call_id=call_id,
            end_reason="reported",
        )
        db.add(row)
        db.commit()
        mark_audit(db.info["request"], "consultation.call.record", "call_log", row.id)
        return ok(call_data(row))
