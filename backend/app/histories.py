"""M2-06: a patient's medical history -- the timeline's data source.

Four routes, from the contract: list and create hang off the patient, edit and
delete address one entry by its own id. Four decisions are worth stating.

* **An entry belongs to exactly one patient.** The two id-addressed routes
  resolve the entry to its patient and run the same department scope check the
  patient-scoped ones do, so another department's entry is a 404 and never a
  403 -- the caller is not told that it exists.
* **A soft-deleted patient takes their history with them.** The contract says
  child rows are "left in place and filtered out with the parent", so the
  lookup refuses a row whose parent is deleted rather than serving an orphan.
* **`onset_date` is optional and the timeline still reads newest-first.** An
  entry recorded without a date is kept and sorted to the bottom, so
  "hypertension, date unknown" can be written down without inventing a date.
* **The audit entry never carries `notes`.** `app.audit` is explicit that
  bodies are not retained; `diagnosis` is the identifying field and is enough
  to read the change back, exactly as the deleted allergen's name is.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import mark_audit
from app.auth import CurrentUser, ok
from app.models import Patient, PatientHistory, User
from app.patients import visible_patient
from app.schemas import (
    ErrorResponse,
    HistoryCreate,
    HistoryListResponse,
    HistoryRead,
    HistoryResponse,
    HistoryUpdate,
    OkData,
    OkResponse,
)
from app.security import require_permission

router = APIRouter()

# A history is a clinical write like any other: every signed-in role holds
# `patient.write`, and the day a read-only role appears it is refused here.
# `security.py` grants the same permission by path prefix; both are kept
# because the prefix rule is what covers a route added here later without
# remembering to list it.
WRITE = [Depends(require_permission("patient.write"))]


def acting_user(request: Request, user: CurrentUser):
    """Name the actor for the audit middleware, which reads request.state.identity."""
    request.state.identity = user
    return user


Actor = Annotated[User, Depends(acting_user)]


def _read(row: PatientHistory) -> HistoryRead:
    return HistoryRead.model_validate(row, from_attributes=True)


def _audit_detail(row: PatientHistory) -> dict:
    """What the trail keeps about one entry.

    `notes` is deliberately absent: `app.audit` retains no bodies, and these
    are free text. `onset_date` is converted because `detail` is a JSON column
    and a `date` raises at insert.
    """
    return {
        "diagnosis": row.diagnosis,
        "onset_date": row.onset_date.isoformat() if row.onset_date else None,
    }


def histories_for_patient(db: Session, patient: Patient) -> list[HistoryRead]:
    """The timeline for one patient, newest onset first.

    Two details in the ordering are deliberate. An entry with no date sorts
    last rather than first: SQLite and MySQL both sort NULL lowest, so the
    explicit `IS NULL` term makes "undated at the bottom" the rule on every
    dialect instead of the accident of one -- `NULLS LAST` would not compile on
    MySQL, which the schema also targets. `id` breaks ties, so two entries
    sharing a date keep a stable order between reads.

    The caller has already resolved a patient it may see, so this reader holds
    the same contract as `groups.groups_for_patient` and does not repeat the
    scope check. Both the list route and `PatientDetail.histories` call it, so
    the two orders cannot drift apart.
    """
    rows = db.scalars(
        select(PatientHistory)
        .where(PatientHistory.patient_id == patient.id)
        .order_by(
            PatientHistory.onset_date.is_(None),
            PatientHistory.onset_date.desc(),
            PatientHistory.id.desc(),
        )
    )
    return [_read(row) for row in rows]


def _entry_with_patient(db: Session, history_id: int) -> tuple[PatientHistory, Patient]:
    """One entry and its patient, or a 404.

    A missing entry, an orphaned one and one whose patient is out of the
    caller's department all answer the same 404: the contract scopes a child
    row by its parent, so the caller learns nothing about which of the three
    it hit.
    """
    row = db.get(PatientHistory, history_id)
    patient = db.get(Patient, row.patient_id) if row is not None else None
    if row is None or patient is None or patient.deleted_at is not None:
        raise HTTPException(404, "History entry not found")
    visible_patient(db, db.info["user"], patient.patient_no)
    return row, patient


@router.get(
    "/api/patients/{patient_no}/histories",
    response_model=HistoryListResponse,
    summary="病史时间线 / List a patient's medical history",
    description=(
        "按发病日期降序返回，供详情页时间线直接渲染；没有发病日期的条目排在最后，"
        "同一天的多条按写入次序稳定排列。\n\n"
        "Ordered by onset date descending for the timeline view. An entry with no "
        "onset date sorts last, and entries sharing a date keep a stable order."
    ),
    responses={404: {"model": ErrorResponse}},
)
def list_patient_histories(request: Request, user: Actor, patient_no: str):
    """病史列表 / List the patient's history, newest onset first."""
    with request.app.state.sessions() as db:
        db.info["user"] = user
        patient = visible_patient(db, user, patient_no)
        return ok(histories_for_patient(db, patient))


@router.post(
    "/api/patients/{patient_no}/histories",
    response_model=HistoryResponse,
    dependencies=WRITE,
    summary="新增病史 / Add a history entry",
    description=(
        "只有诊断必填；发病日期可留空。写入 history.create 审计。\n\n"
        "Only the diagnosis is required; the onset date may be omitted. Writes a "
        "`history.create` audit entry."
    ),
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def create_patient_history(request: Request, user: Actor, patient_no: str, body: HistoryCreate):
    """新增病史 / Add one entry to the patient's history."""
    with request.app.state.sessions() as db:
        db.info["user"] = user
        patient = visible_patient(db, user, patient_no)
        row = PatientHistory(
            patient_id=patient.id,
            diagnosis=body.diagnosis,
            onset_date=body.onset_date,
            notes=body.notes,
        )
        db.add(row)
        db.flush()
        detail = _audit_detail(row)
        db.commit()
        db.refresh(row)
        mark_audit(
            request, "history.create", "history", row.id, patient_id=patient.id, detail=detail
        )
        return ok(_read(row))


@router.patch(
    "/api/histories/{id}",
    response_model=HistoryResponse,
    dependencies=WRITE,
    summary="修改病史 / Update a history entry",
    description=(
        "部分更新，只有请求体里出现的字段会变；`onset_date` 传 `null` 表示清除该日期，"
        "`diagnosis` 与 `notes` 传 `null` 会被拒绝。写入 history.update 审计。\n\n"
        "Partial update: only the fields present in the body change. "
        "`onset_date: null` clears the date; `diagnosis: null` and `notes: null` are "
        "refused. Writes a `history.update` audit entry."
    ),
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def update_patient_history(request: Request, user: Actor, id: int, body: HistoryUpdate):
    """修改病史 / Edit one entry."""
    with request.app.state.sessions() as db:
        db.info["user"] = user
        row, patient = _entry_with_patient(db, id)
        # `onset_date` is the exception: it is nullable precisely so a wrong
        # date can be taken back off an entry.
        for field in ("diagnosis", "notes"):
            if field in body.model_fields_set and getattr(body, field) is None:
                raise HTTPException(422, f"{field} must not be null")
        for field, value in body.model_dump(exclude_unset=True).items():
            setattr(row, field, value)
        detail = _audit_detail(row)
        db.commit()
        db.refresh(row)
        mark_audit(
            request, "history.update", "history", row.id, patient_id=patient.id, detail=detail
        )
        return ok(_read(row))


@router.delete(
    "/api/histories/{id}",
    response_model=OkResponse,
    dependencies=WRITE,
    summary="删除病史 / Delete a history entry",
    description=(
        "写入 history.delete 审计，`detail` 保留被删条目的诊断与发病日期。\n\n"
        "Writes a `history.delete` audit entry whose `detail` keeps the removed "
        "entry's diagnosis and onset date."
    ),
    responses={404: {"model": ErrorResponse}},
)
def delete_patient_history(request: Request, user: Actor, id: int):
    """删除病史 / Delete one entry."""
    with request.app.state.sessions() as db:
        db.info["user"] = user
        row, patient = _entry_with_patient(db, id)
        # Snapshot before the row goes: the trail outlives the record it names.
        detail = _audit_detail(row)
        db.delete(row)
        db.commit()
        mark_audit(request, "history.delete", "history", id, patient_id=patient.id, detail=detail)
        return ok(OkData())
