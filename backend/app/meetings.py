"""T30/T31/T32: the remote-consultation state machine, materials and report.

One module because the three tasks share one object graph and one rule set: who
may see a meeting (its initiator and its invitees), who may reach the patient
(T09's department scope, widened by the automatic `temp_grant`), and which
transitions are legal.

    requested --accept--> accepted --start--> in_progress --complete--> completed
        |
        +---decline--> declined

Anything else is a 409. There is deliberately no `archived` state: what gets
archived is the report, which lands in `meeting_reports` and is read back from
the patient record through `GET /api/meetings?patient_no=...`.
"""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import func, or_, select

from app import meeting_schemas as contract
from app.audit import mark_audit, persist_audit
from app.auth import CurrentUser, ok
from app.dependencies import Pagination
from app.models import (
    Department,
    Meeting,
    MeetingMaterial,
    MeetingParticipant,
    MeetingReport,
    Patient,
    TempGrant,
    User,
)
from app.patients import patient_scope
from app.uploads import MEETING_TYPES, save_upload, stored_path

router = APIRouter()

# M5-01: 发起时自动为每位受邀专家建 temp_grant，有效期 = 会诊时间 + 24h.
GRANT_BUFFER = timedelta(hours=24)

TEMPLATES = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent / "templates"),
    autoescape=select_autoescape(["html", "xml"]),
)


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def derived_title(purpose: str) -> str:
    """`title` is optional and only a display convenience: when the client omits
    it, one is derived from the purpose rather than demanding a second string."""
    line = purpose.strip().splitlines()[0]
    return line if len(line) <= 80 else line[:77] + "..."


def material_disposition(filename: str) -> str:
    """`Content-Disposition` for a download, with the original name in it.

    Deliberately not `app.audit_export.content_disposition`: that helper belongs
    to T12's CSV export and is only ever handed ASCII filenames, while this one
    has to carry 心电图-2026-09-01.pdf. The difference matters because HTTP headers
    are latin-1: a Chinese name in the plain `filename` parameter makes Starlette
    raise `UnicodeEncodeError`, and the download becomes a 500. So the plain
    parameter is reduced to ASCII as a fallback, and the RFC 5987 `filename*`
    -- percent-encoded UTF-8, which is plain ASCII on the wire -- carries the real
    name, which is what the browser uses (T31 §4, scenario M5-T4).
    """
    fallback = "".join(ch if ch.isascii() and ch.isprintable() else "_" for ch in filename)
    fallback = (fallback or "file").replace(chr(34), chr(39))
    return (
        f"attachment; filename={chr(34)}{fallback}{chr(34)}; "
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )


def meeting_or_404(db, meeting_id: int) -> Meeting:
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(404, "Meeting not found")
    return meeting


def invitation_of(meeting: Meeting, user) -> MeetingParticipant | None:
    for row in meeting.participants:
        if row.user_id == user.id:
            return row
    return None


def is_participant(meeting: Meeting, user) -> bool:
    return meeting.initiator_id == user.id or invitation_of(meeting, user) is not None


def require_participant(meeting: Meeting, user) -> None:
    """403, and only on the sub-resources.

    T31 scenario S2 copies a material URL into a non-participant's session and
    requires the refusal to come from the server, not from a hidden button. The
    detail route deliberately answers 404 instead -- see `visible_meeting`.
    """
    if not is_participant(meeting, user):
        raise HTTPException(403, "Only meeting participants may do this")


def visible_meeting(db, user, meeting_id: int) -> Meeting:
    """The detail read. A stranger gets 404, never 403: the contract accepts
    either answer as long as it does not confirm that the meeting exists."""
    meeting = meeting_or_404(db, meeting_id)
    if not is_participant(meeting, user):
        raise HTTPException(404, "Meeting not found")
    return meeting


def reaches_patient(db, user, patient_id: int) -> bool:
    """The ordinary T09 test, used by the report read: a colleague who can reach
    the patient reads the archived report without having attended the meeting."""
    return (
        db.scalar(
            select(Patient.id).where(
                Patient.id == patient_id,
                Patient.deleted_at.is_(None),
                patient_scope(user),
            )
        )
        is not None
    )


def participant_data(row: MeetingParticipant) -> dict:
    return {
        "user_id": row.user_id,
        "name": row.user.name,
        "department": row.user.department.name,
        "status": row.status,
    }


def meeting_data(meeting: Meeting) -> dict:
    return {
        "id": meeting.id,
        "title": meeting.title,
        "patient_no": meeting.patient.patient_no,
        "initiator_id": meeting.initiator_id,
        "initiator_name": meeting.initiator.name,
        "status": meeting.status,
        "scheduled_at": utc(meeting.scheduled_at),
        "started_at": utc(meeting.started_at) if meeting.started_at else None,
        "completed_at": utc(meeting.completed_at) if meeting.completed_at else None,
        "purpose": meeting.purpose,
        "participants": [participant_data(row) for row in meeting.participants],
        "created_at": utc(meeting.created_at),
    }


def material_data(material: MeetingMaterial) -> dict:
    return {
        "id": material.id,
        "meeting_id": material.meeting_id,
        "filename": material.filename,
        "content_type": material.content_type,
        "size_bytes": material.size_bytes,
        "uploaded_by": material.uploaded_by,
        "uploaded_by_name": material.uploader.name,
        "uploaded_at": utc(material.uploaded_at),
    }


def report_data(report: MeetingReport) -> dict:
    return {
        "id": report.id,
        "meeting_id": report.meeting_id,
        "expert_opinions": report.expert_opinions or [],
        "conclusion": report.conclusion,
        "status": report.status,
        "version": report.version,
        "created_by": report.created_by,
        "created_by_name": report.author.name,
        "created_at": utc(report.created_at),
    }


def latest_report(db, meeting_id: int, version: int | None = None) -> MeetingReport | None:
    """No version asked for means the newest one; the earlier versions stay
    readable, which is what "不静默覆盖" means in practice."""
    if version is not None:
        return db.scalar(
            select(MeetingReport).where(
                MeetingReport.meeting_id == meeting_id, MeetingReport.version == version
            )
        )
    return db.scalar(
        select(MeetingReport)
        .where(MeetingReport.meeting_id == meeting_id)
        .order_by(MeetingReport.version.desc())
    )


def age_of(birth_date: date | None, today: date) -> int | None:
    if birth_date is None:
        return None
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


def upload_directory(request: Request) -> Path:
    return Path(request.app.state.settings.upload_dir) / "meeting"


# --- M5-01: the state machine and the invitation inbox -----------------------


@router.get("/api/meetings/doctors", response_model=contract.DoctorListResponse)
def list_doctors(
    request: Request,
    user: CurrentUser,
    pagination: Annotated[Pagination, Depends()],
    q: str | None = None,
    department: str | None = None,
):
    """受邀专家候选目录 / The invite picker's directory.

    Declared before `/api/meetings/{id}` on purpose: `{id}` is an integer, so a
    literal segment registered after it would be read as a malformed id and
    answer 422 without ever reaching this function.

    M1-07's `/api/users` is administrator-only and T30 S1's initiator is a
    junior, so the picker reads this instead. It exposes identity and department
    only, never email, and M1-07 supersedes it.
    """
    with request.app.state.sessions() as db:
        conditions = [User.status == "active"]
        if q and q.strip():
            like = f"%{q.strip()}%"
            conditions.append(or_(User.name.like(like), User.username.like(like)))
        if department:
            conditions.append(
                User.department_id.in_(select(Department.id).where(Department.name == department))
            )
        total = db.scalar(select(func.count()).select_from(User).where(*conditions)) or 0
        rows = list(
            db.scalars(
                select(User)
                .where(*conditions)
                .order_by(User.name, User.id)
                .offset(pagination.offset)
                .limit(pagination.size)
            )
        )
        return ok(
            {
                "items": [
                    {
                        "id": row.id,
                        "username": row.username,
                        "name": row.name,
                        "title": row.role.name,
                        "department": row.department.name,
                    }
                    for row in rows
                ],
                "total": total,
                "page": pagination.page,
                "size": pagination.size,
            }
        )


@router.get("/api/meetings", response_model=contract.MeetingListResponse)
def list_meetings(
    request: Request,
    user: CurrentUser,
    pagination: Annotated[Pagination, Depends()],
    status: Annotated[contract.MeetingStatus | None, Query()] = None,
    patient_no: Annotated[str | None, Query(examples=["P20260001"])] = None,
):
    """会诊列表 / List meetings.

    Without a filter: the meetings the caller started plus the ones they were
    invited to. With `patient_no` the scope deliberately widens to that
    patient's meetings -- T32 archives the report to the patient record, so a
    department colleague who neither started nor attended the meeting must be
    able to read it back from the "会诊记录" tab. Access still follows the
    ordinary T09 department rule; outside it the page comes back empty rather
    than 404, because the patient-scoped 404 belongs to the patient routes.
    """
    with request.app.state.sessions() as db:
        conditions = []
        if status is not None:
            conditions.append(Meeting.status == status.value)
        if patient_no is not None:
            query = (
                select(Meeting)
                .join(Patient, Meeting.patient_id == Patient.id)
                .where(
                    Patient.patient_no == patient_no,
                    Patient.deleted_at.is_(None),
                    patient_scope(user),
                    *conditions,
                )
            )
        else:
            invited = select(MeetingParticipant.meeting_id).where(
                MeetingParticipant.user_id == user.id
            )
            query = select(Meeting).where(
                or_(Meeting.initiator_id == user.id, Meeting.id.in_(invited)), *conditions
            )
        total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = db.scalars(
            query.order_by(Meeting.created_at.desc(), Meeting.id.desc())
            .offset(pagination.offset)
            .limit(pagination.size)
        )
        return ok(
            {
                "items": [meeting_data(row) for row in rows],
                "total": total,
                "page": pagination.page,
                "size": pagination.size,
            }
        )


@router.post("/api/meetings", response_model=contract.MeetingResponse)
def create_meeting(body: contract.MeetingCreateRequest, request: Request, user: CurrentUser):
    """发起会诊 / Request a remote consultation.

    Anyone who can reach the patient may initiate -- T30 S1 has `dr_wang`, a
    junior physician, start the meeting -- so this route is not gated on
    `senior`.

    Inviting an expert automatically creates a `temp_grant` for each one, valid
    until the planned meeting time plus 24 hours. That cross-module link with
    T10 is the point of the endpoint: without the grants the invitation is just
    a row, and M5-T2 ("dr_chen 可查该患者详情，原为 404") cannot pass.
    """
    with request.app.state.sessions() as db:
        db.info["request"] = request
        patient = db.scalar(
            select(Patient).where(
                Patient.patient_no == body.patient_no,
                Patient.deleted_at.is_(None),
                patient_scope(user),
            )
        )
        if patient is None:
            raise HTTPException(404, "Patient not found")

        invitee_ids = [item for item in dict.fromkeys(body.participant_ids) if item != user.id]
        if not invitee_ids:
            raise HTTPException(422, "Invite at least one other physician")
        invitees = list(
            db.scalars(select(User).where(User.id.in_(invitee_ids), User.status == "active"))
        )
        if len(invitees) != len(invitee_ids):
            raise HTTPException(404, "Invited physician not found")

        scheduled_at = body.scheduled_at.astimezone(UTC) if body.scheduled_at else datetime.now(UTC)
        meeting = Meeting(
            patient_id=patient.id,
            initiator_id=user.id,
            title=body.title or derived_title(body.purpose),
            purpose=body.purpose,
            status="requested",
            scheduled_at=scheduled_at,
        )
        db.add(meeting)
        db.flush()

        grants = []
        for invitee in invitees:
            db.add(MeetingParticipant(meeting_id=meeting.id, user_id=invitee.id, status="invited"))
            grant = TempGrant(
                grantee_id=invitee.id,
                patient_id=patient.id,
                reason=f"Remote consultation #{meeting.id}: {body.purpose[:400]}",
                granted_by=user.id,
                expire_at=scheduled_at + GRANT_BUFFER,
            )
            db.add(grant)
            db.flush()
            grants.append(grant)

        mark_audit(
            request,
            "meeting.create",
            "meeting",
            meeting.id,
            patient_id=patient.id,
            detail={
                "patient_no": patient.patient_no,
                "participant_ids": invitee_ids,
                "grant_ids": [grant.id for grant in grants],
                "scheduled_at": scheduled_at.isoformat(),
            },
        )
        db.commit()
        db.refresh(meeting)
        # Each automatic grant gets its own trail row. One request can only
        # carry one middleware audit entry, so these are written directly --
        # after the business transaction lands, and never able to abort it.
        sessions = request.app.state.sessions
        grant_events = [
            {
                "action": "temp_grant.create",
                "patient_id": patient.id,
                "user_id": user.id,
                "object_type": "temp_grant",
                "object_id": str(grant.id),
                "detail": {
                    "grant_id": grant.id,
                    "grantee_id": grant.grantee_id,
                    "user_id": user.id,
                    "meeting_id": meeting.id,
                },
                "method": "POST",
                "path": "/api/meetings",
                "result": "success",
                "status_code": 200,
            }
            for grant in grants
        ]
    for event in grant_events:
        persist_audit(sessions, event)
    return ok(meeting_data(meeting))


@router.get("/api/meetings/{id}", response_model=contract.MeetingResponse)
def get_meeting(id: int, request: Request, user: CurrentUser):
    """会诊详情 / Read a meeting. Participants only; a stranger gets 404."""
    with request.app.state.sessions() as db:
        return ok(meeting_data(visible_meeting(db, user, id)))


def apply_invitation(request, user, meeting_id: int, action: str):
    with request.app.state.sessions() as db:
        db.info["request"] = request
        meeting = meeting_or_404(db, meeting_id)
        invitation = invitation_of(meeting, user)
        if invitation is None:
            raise HTTPException(403, "Only an invited physician may answer an invitation")
        if invitation.status != "invited":
            raise HTTPException(409, f"This invitation was already {invitation.status}")
        if meeting.status not in ("requested", "accepted"):
            raise HTTPException(
                409, f"The meeting is not awaiting acceptance (status={meeting.status})"
            )
        previous = meeting.status
        if action == "accept":
            invitation.status = "accepted"
            if meeting.status == "requested":
                meeting.status = "accepted"
        else:
            invitation.status = "declined"
            # Everyone refused: the machine has a `declined` branch, so take it
            # instead of leaving the meeting stuck in `requested` where `start`
            # can never be reached.
            if meeting.status == "requested" and all(
                row.status == "declined" for row in meeting.participants
            ):
                meeting.status = "declined"
        mark_audit(
            request,
            f"meeting.{action}",
            "meeting",
            meeting.id,
            patient_id=meeting.patient_id,
            detail={
                "meeting_id": meeting.id,
                "from": previous,
                "to": meeting.status,
                "invitation_status": invitation.status,
            },
        )
        db.commit()
        db.refresh(meeting)
        return ok(meeting_data(meeting))


def apply_progress(request, user, meeting_id: int, action: str):
    with request.app.state.sessions() as db:
        db.info["request"] = request
        meeting = meeting_or_404(db, meeting_id)
        if meeting.initiator_id != user.id:
            raise HTTPException(403, "Only the initiator may change the meeting's state")
        expected, target = {
            "start": ("accepted", "in_progress"),
            "complete": ("in_progress", "completed"),
        }[action]
        if meeting.status != expected:
            # T30 S2 forces `requested` straight to `completed` and requires
            # 409, not 400: the request is well formed, the transition is not.
            raise HTTPException(
                409, f"Illegal transition: {meeting.status} -> {target} is not allowed"
            )
        previous = meeting.status
        meeting.status = target
        if action == "start":
            meeting.started_at = datetime.now(UTC)
        else:
            meeting.completed_at = datetime.now(UTC)
        mark_audit(
            request,
            f"meeting.{action}",
            "meeting",
            meeting.id,
            patient_id=meeting.patient_id,
            detail={"meeting_id": meeting.id, "from": previous, "to": target},
        )
        db.commit()
        db.refresh(meeting)
        return ok(meeting_data(meeting))


@router.post("/api/meetings/{id}/accept", response_model=contract.MeetingResponse)
def accept_meeting(id: int, request: Request, user: CurrentUser):
    """接受邀请 / Accept: `requested` -> `accepted`."""
    return apply_invitation(request, user, id, "accept")


@router.post("/api/meetings/{id}/decline", response_model=contract.MeetingResponse)
def decline_meeting(id: int, request: Request, user: CurrentUser):
    """拒绝邀请 / Decline: `requested` -> `declined`, a real state, not a delete."""
    return apply_invitation(request, user, id, "decline")


@router.post("/api/meetings/{id}/start", response_model=contract.MeetingResponse)
def start_meeting(id: int, request: Request, user: CurrentUser):
    """开始会诊 / Start: `accepted` -> `in_progress`. Initiator only."""
    return apply_progress(request, user, id, "start")


@router.post("/api/meetings/{id}/complete", response_model=contract.MeetingResponse)
def complete_meeting(id: int, request: Request, user: CurrentUser):
    """结束会诊 / Complete: `in_progress` -> `completed`, after which a report
    can be written. The automatic grants are left to run out on their own
    schedule -- M5-T8 waits for the expiry scan, and revoking early would make
    "有效期 = 会诊时间 + 24h" untrue."""
    return apply_progress(request, user, id, "complete")


@router.get(
    "/api/meetings/{id}/participants",
    response_model=contract.MeetingParticipantListResponse,
)
def list_meeting_participants(id: int, request: Request, user: CurrentUser):
    """参与人列表 / Participants, each with their invitation status.

    The initiator is not repeated here: `Meeting.initiator_id` already names
    them, and mirroring them into this list would invent an invitation nobody
    sent.
    """
    with request.app.state.sessions() as db:
        meeting = visible_meeting(db, user, id)
        return ok([participant_data(row) for row in meeting.participants])


# --- M5-02: shared materials ------------------------------------------------


@router.get("/api/meetings/{id}/materials", response_model=contract.MeetingMaterialListResponse)
def list_meeting_materials(id: int, request: Request, user: CurrentUser):
    """资料列表 / Shared materials. Participants only, enforced here."""
    with request.app.state.sessions() as db:
        meeting = meeting_or_404(db, id)
        require_participant(meeting, user)
        rows = db.scalars(
            select(MeetingMaterial)
            .where(MeetingMaterial.meeting_id == meeting.id)
            .order_by(MeetingMaterial.id)
        )
        return ok([material_data(row) for row in rows])


@router.post("/api/meetings/{id}/materials", response_model=contract.MeetingMaterialResponse)
def upload_meeting_material(
    id: int,
    request: Request,
    user: CurrentUser,
    file: Annotated[UploadFile, File()],
):
    """共享资料 / Share a record or image.

    The uploader is `app.uploads`, the same component T26 uses -- same size
    cap, same randomised name, same content-type check, same audit hook. Only
    the whitelist differs: this route accepts PDF, images and documents, so a
    `.pdf` passes where T26's image-only list would refuse it.
    """
    with request.app.state.sessions() as db:
        db.info["request"] = request
        meeting = meeting_or_404(db, id)
        require_participant(meeting, user)
        stored = save_upload(file, upload_directory(request), MEETING_TYPES)
        material = MeetingMaterial(
            meeting_id=meeting.id,
            filename=stored.filename,
            stored_name=stored.stored_name,
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
            uploaded_by=user.id,
        )
        db.add(material)
        db.flush()
        mark_audit(
            request,
            "meeting.material.upload",
            "meeting_material",
            material.id,
            patient_id=meeting.patient_id,
            detail={
                "meeting_id": meeting.id,
                "filename": stored.filename,
                "content_type": stored.content_type,
                "size_bytes": stored.size_bytes,
            },
        )
        db.commit()
        db.refresh(material)
        return ok(material_data(material))


@router.get("/api/materials/{id}/download")
def download_material(id: int, request: Request, user: CurrentUser):
    """下载资料 / Download a shared material.

    A physician who is not a participant of the owning meeting gets 403 --
    M5-T5 copies this URL into a non-participant's session precisely because
    protecting the list and leaving the download open is the usual hole.

    The original filename travels in `Content-Disposition`, both as a plain
    `filename` and as the RFC 5987 `filename*`, so 心电图-2026-09-01.pdf arrives
    readable instead of being renamed after the numeric id in the URL.
    """
    with request.app.state.sessions() as db:
        db.info["request"] = request
        material = db.get(MeetingMaterial, id)
        if material is None:
            raise HTTPException(404, "Material not found")
        meeting = meeting_or_404(db, material.meeting_id)
        require_participant(meeting, user)
        path = stored_path(upload_directory(request), material.stored_name)
        if not path.is_file():
            raise HTTPException(404, "Stored file is missing")
        mark_audit(
            request,
            "meeting.material.download",
            "meeting_material",
            material.id,
            patient_id=meeting.patient_id,
            detail={"meeting_id": meeting.id, "filename": material.filename},
        )
        return FileResponse(
            path,
            media_type=material.content_type,
            headers={"Content-Disposition": material_disposition(material.filename)},
        )


# --- M5-03: the report and its printable sheet -------------------------------


@router.get("/api/meetings/{id}/report", response_model=contract.MeetingReportResponse)
def get_meeting_report(
    id: int,
    request: Request,
    user: CurrentUser,
    version: Annotated[
        int | None, Query(ge=1, description="Earlier versions stay readable.")
    ] = None,
):
    """会诊报告 / Read the report.

    Readable by the meeting's participants *and* by anyone who can reach the
    patient under the ordinary T09 rule: T32 §3 archives the report into the
    patient record, so the "会诊记录" tab and this endpoint read the same row.
    """
    with request.app.state.sessions() as db:
        meeting = meeting_or_404(db, id)
        if not is_participant(meeting, user) and not reaches_patient(db, user, meeting.patient_id):
            raise HTTPException(403, "Not allowed to read this report")
        report = latest_report(db, meeting.id, version)
        if report is None:
            raise HTTPException(404, "Report not generated yet")
        return ok(report_data(report))


@router.post("/api/meetings/{id}/report", response_model=contract.MeetingReportResponse)
def save_meeting_report(
    id: int, body: contract.MeetingReportWriteRequest, request: Request, user: CurrentUser
):
    """生成报告 / Write the report.

    Participants only -- T32 S2 has a non-participant attempt this and requires
    403, so the check cannot live in the UI.

    The conclusion is never rewritten in place: every save is a new version and
    the earlier text stays readable through `?version=`.
    """
    with request.app.state.sessions() as db:
        db.info["request"] = request
        meeting = meeting_or_404(db, id)
        require_participant(meeting, user)
        if meeting.status != "completed":
            raise HTTPException(
                409,
                "A report can only be written once the meeting is completed "
                f"(status={meeting.status})",
            )
        previous = db.scalar(
            select(func.max(MeetingReport.version)).where(MeetingReport.meeting_id == meeting.id)
        )
        report = MeetingReport(
            meeting_id=meeting.id,
            expert_opinions=[opinion.model_dump() for opinion in body.expert_opinions],
            conclusion=body.conclusion,
            status=body.status,
            version=(previous or 0) + 1,
            created_by=user.id,
        )
        db.add(report)
        db.flush()
        mark_audit(
            request,
            "meeting.report.create",
            "meeting_report",
            report.id,
            patient_id=meeting.patient_id,
            detail={
                "meeting_id": meeting.id,
                "version": report.version,
                "status": report.status,
                "experts": [opinion.expert_id for opinion in body.expert_opinions],
            },
        )
        db.commit()
        db.refresh(report)
        return ok(report_data(report))


@router.get("/api/meetings/{id}/report/print")
def print_meeting_report(
    id: int,
    request: Request,
    user: CurrentUser,
    version: Annotated[int | None, Query(ge=1)] = None,
):
    """可打印报告 / Render the report as printable HTML.

    Jinja2 renders the sheet and the browser prints it; there is no server-side
    PDF library. The page carries `@page { size: A4 }` and `@media print` rules,
    so Ctrl+P previews a clean sheet with nothing clipped.
    """
    with request.app.state.sessions() as db:
        meeting = meeting_or_404(db, id)
        require_participant(meeting, user)
        report = latest_report(db, meeting.id, version)
        if report is None:
            raise HTTPException(404, "Report not generated yet")
        patient = meeting.patient
        context = {
            "meeting": meeting_data(meeting),
            "report": report_data(report),
            "patient": {
                "patient_no": patient.patient_no,
                "name": patient.name,
                "gender": patient.gender,
                "age": age_of(patient.birth_date, datetime.now(UTC).date()),
                "department": patient.department.name,
                "admitted_at": patient.admitted_at,
            },
            "initiator": meeting.initiator.name,
            "versions": db.scalar(
                select(func.max(MeetingReport.version)).where(
                    MeetingReport.meeting_id == meeting.id
                )
            ),
            "printed_at": datetime.now(UTC),
            "printed_by": user.name,
        }
        html = TEMPLATES.get_template("meeting_report.html").render(**context)
    return HTMLResponse(html)
