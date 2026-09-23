"""M4 templates, versioned records, prescription validation and review."""

from copy import deepcopy
from datetime import date
from math import isfinite
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm.exc import StaleDataError

from app import emr_schemas as schema
from app.audit import mark_audit
from app.auth import CurrentUser, ok
from app.dependencies import Pagination
from app.emr_models import Drug, EmrRecord, EmrTemplate, EmrVersion, MedicalOrder, now
from app.emr_validation import validate_orders
from app.models import Patient
from app.patients import patient_scope, visible_patient
from app.security import require_permission

router = APIRouter()
Writer = Annotated[object, Depends(require_permission("emr.write"))]
Reviewer = Annotated[object, Depends(require_permission("emr.review"))]
Manager = Annotated[object, Depends(require_permission("template.manage"))]
Page = Annotated[Pagination, Depends()]


def session(request: Request):
    with request.app.state.sessions() as db:
        try:
            yield db
        except StaleDataError:
            db.rollback()
            raise HTTPException(409, "Record changed; refresh before saving") from None


DB = Annotated[object, Depends(session)]


def template_data(row):
    return {k: getattr(row, k) for k in ("id", "name", "description", "fields_json", "is_active")}


def record_data(row):
    data = {
        k: getattr(row, k)
        for k in (
            "id",
            "template_id",
            "author_id",
            "status",
            "version",
            "revision",
            "content_json",
            "template_snapshot",
            "updated_at",
            "created_at",
        )
    }
    data.update(
        patient_no=row.patient.patient_no,
        patient_name=row.patient.name,
        template_name=row.template_snapshot["name"],
        author_name=row.author.name,
    )
    for key in ("reviewer_id", "review_comment", "reviewed_at"):
        if getattr(row, key) is not None:
            data[key] = getattr(row, key)
    return data


def record_query(user):
    return select(EmrRecord).join(Patient).where(Patient.deleted_at.is_(None), patient_scope(user))


def visible_record(db, user, id):
    row = db.scalar(record_query(user).where(EmrRecord.id == id))
    if row is None:
        raise HTTPException(404, "Record not found")
    return row


def author_only(row, user):
    if row.author_id != user.id:
        raise HTTPException(403, "Only the record author may do this")


def unlocked(row):
    if row.status == "archived":
        raise HTTPException(409, "Record is archived and cannot be modified")


def editable(row, user):
    unlocked(row)
    author_only(row, user)
    if row.status not in ("draft", "rejected"):
        raise HTTPException(409, "Record is pending review")


def validate_content(row, content, required=True):
    fields = row.template_snapshot["fields_json"]["fields"]
    unknown = content.keys() - {f["key"] for f in fields}
    if unknown:
        raise HTTPException(422, f"Unknown content_json fields: {', '.join(sorted(unknown))}")
    for field in fields:
        key = field["key"]
        value = content.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            if required and field.get("required"):
                raise HTTPException(422, f"content_json.{key} is required")
            continue
        kind = field["type"]
        valid = isinstance(value, str)
        if kind == "number":
            valid = type(value) in (int, float) and isfinite(value)
        elif kind == "select":
            valid = value in field["options"]
        elif kind == "date":
            try:
                date.fromisoformat(value)
            except (ValueError, TypeError):
                valid = False
        if not valid:
            raise HTTPException(422, f"Invalid content_json.{key}")


def snapshot(db, row, content=None):
    db.add(
        EmrVersion(
            record_id=row.id,
            version=row.version,
            content_json=deepcopy(row.content_json if content is None else content),
            author_id=row.author_id,
        )
    )


def audit(request, action, row, detail=None):
    mark_audit(request, action, "emr_record", row.id, patient_id=row.patient_id, detail=detail)


@router.get("/api/emr/templates")
def templates(db: DB, user: CurrentUser):
    return ok([template_data(t) for t in db.scalars(select(EmrTemplate).order_by(EmrTemplate.id))])


@router.post("/api/emr/templates")
def create_template(body: schema.TemplateWrite, request: Request, db: DB, user: Manager):
    row = EmrTemplate(**body.model_dump())
    db.add(row)
    db.commit()
    mark_audit(request, "emr_template.create", "emr_template", row.id)
    return ok(template_data(row))


@router.get("/api/emr/templates/{id}")
def template(id: int, db: DB, user: CurrentUser):
    row = db.get(EmrTemplate, id)
    if row is None:
        raise HTTPException(404, "Template not found")
    return ok(template_data(row))


@router.patch("/api/emr/templates/{id}")
def update_template(id: int, body: schema.TemplateWrite, request: Request, db: DB, user: Manager):
    row = db.get(EmrTemplate, id)
    if row is None:
        raise HTTPException(404, "Template not found")
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    db.commit()
    mark_audit(request, "emr_template.update", "emr_template", id)
    return ok(template_data(row))


def record_page(db, query, pagination):
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.offset(pagination.offset).limit(pagination.size))
    return ok(
        {
            "items": [
                {
                    k: v
                    for k, v in record_data(row).items()
                    if k not in ("content_json", "template_snapshot")
                }
                for row in rows
            ],
            "total": total,
            "page": pagination.page,
            "size": pagination.size,
        }
    )


Status = Literal["draft", "pending", "archived", "rejected"]


@router.get("/api/emr/records")
def records(
    db: DB,
    user: CurrentUser,
    pagination: Page,
    patient_no: str | None = None,
    status: Status | None = None,
    author_id: int | None = None,
):
    query = record_query(user)
    if patient_no:
        query = query.where(Patient.patient_no == patient_no)
    if status:
        query = query.where(EmrRecord.status == status)
    if author_id:
        query = query.where(EmrRecord.author_id == author_id)
    return record_page(
        db, query.order_by(EmrRecord.updated_at.desc(), EmrRecord.id.desc()), pagination
    )


@router.post("/api/emr/records")
def create_record(body: schema.RecordCreate, request: Request, db: DB, user: Writer):
    patient = visible_patient(db, user, body.patient_no)
    template = db.get(EmrTemplate, body.template_id)
    if template is None or not template.is_active:
        raise HTTPException(422, "template_id must identify an active template")
    row = EmrRecord(
        patient_id=patient.id,
        template_id=template.id,
        template_snapshot=template_data(template),
        author_id=user.id,
    )
    db.add(row)
    db.flush()
    snapshot(db, row)
    db.commit()
    audit(request, "emr_record.create", row)
    return ok(record_data(row))


@router.get("/api/emr/records/{id}")
def record(id: int, request: Request, db: DB, user: CurrentUser):
    row = visible_record(db, user, id)
    audit(request, "emr_record.view", row)
    return ok(record_data(row))


@router.patch("/api/emr/records/{id}")
def update_record(id: int, body: schema.RecordUpdate, request: Request, db: DB, user: Writer):
    row = visible_record(db, user, id)
    editable(row, user)
    if (row.version, row.revision) != (body.version, body.revision):
        raise HTTPException(409, "Record changed; refresh before saving")
    validate_content(row, body.content_json)
    row.content_json = deepcopy(body.content_json)
    row.updated_at = now()
    db.commit()
    audit(request, "emr_record.save", row)
    return ok(record_data(row))


@router.post("/api/emr/records/{id}/submit")
def submit_record(id: int, request: Request, db: DB, user: Writer):
    row = visible_record(db, user, id)
    if row.status == "pending":
        author_only(row, user)
        raise HTTPException(400, "Record is already pending review")
    editable(row, user)
    validate_content(row, row.content_json)
    # Freeze the final v1 draft on first submission; subsequent snapshots never change.
    if row.version == 1:
        first = db.scalar(
            select(EmrVersion).where(EmrVersion.record_id == id, EmrVersion.version == 1)
        )
        first.content_json = deepcopy(row.content_json)
    row.version += 1
    row.status = "pending"
    row.submitted_at = row.updated_at = now()
    row.review_comment = row.reviewer_id = row.reviewed_at = None
    snapshot(db, row)
    db.commit()
    audit(request, "emr_record.submit", row)
    return ok(record_data(row))


@router.get("/api/emr/records/{id}/versions")
def versions(id: int, db: DB, user: CurrentUser):
    visible_record(db, user, id)
    return ok(
        [
            {
                "version": v.version,
                "content_json": v.content_json,
                "author_id": v.author_id,
                "author_name": v.author.name,
                "created_at": v.created_at,
            }
            for v in db.scalars(
                select(EmrVersion).where(EmrVersion.record_id == id).order_by(EmrVersion.version)
            )
        ]
    )


@router.post("/api/emr/records/{id}/amend")
def amend(id: int, body: schema.Amendment, request: Request, db: DB, user: Writer):
    row = visible_record(db, user, id)
    author_only(row, user)
    if row.status != "archived":
        raise HTTPException(400, "Only archived records accept amendments")
    if not body.content_json:
        raise HTTPException(422, "content_json must not be empty")
    validate_content(row, body.content_json, required=False)
    row.version += 1
    row.updated_at = now()
    previous = db.scalar(
        select(EmrVersion).where(EmrVersion.record_id == id).order_by(EmrVersion.version.desc())
    )
    snapshot(db, row, {**previous.content_json, **body.content_json})
    db.commit()
    audit(request, "emr_record.amend", row)
    return ok(record_data(row))


@router.get("/api/emr/reviews")
def reviews(db: DB, user: Reviewer, pagination: Page):
    return record_page(
        db,
        record_query(user)
        .where(EmrRecord.status == "pending")
        .order_by(EmrRecord.submitted_at, EmrRecord.id),
        pagination,
    )


@router.get("/api/emr/my-submissions")
def submissions(db: DB, user: CurrentUser, pagination: Page, status: Status | None = None):
    query = record_query(user).where(EmrRecord.author_id == user.id)
    if status:
        query = query.where(EmrRecord.status == status)
    return record_page(db, query.order_by(EmrRecord.updated_at.desc()), pagination)


def review_record(id, body, request, db, user):
    row = visible_record(db, user, id)
    unlocked(row)
    if row.status != "pending":
        raise HTTPException(400, "Only pending records can be reviewed")
    if body.action == "reject" and not body.comment.strip():
        raise HTTPException(422, "comment is required when rejecting")
    row.status = "archived" if body.action == "approve" else "rejected"
    row.reviewer_id, row.review_comment = user.id, body.comment
    row.reviewed_at = row.updated_at = now()
    db.commit()
    audit(
        request,
        "emr_record.review",
        row,
        {
            "action": body.action,
            "reviewer_id": user.id,
            "comment": body.comment,
            "reviewed_at": row.reviewed_at.isoformat(),
        },
    )
    return ok(record_data(row))


@router.post("/api/emr/records/{id}/review")
def review(id: int, body: schema.Review, request: Request, db: DB, user: Reviewer):
    return review_record(id, body, request, db, user)


@router.post("/api/emr/records/{id}/archive")
def archive(id: int, request: Request, db: DB, user: Reviewer):
    return review_record(id, schema.Review(action="approve"), request, db, user)


@router.get("/api/drugs")
def drugs(db: DB, user: CurrentUser, q: str = ""):
    rows = db.scalars(
        select(Drug)
        .where(or_(Drug.name.ilike(f"%{q}%"), Drug.code.ilike(f"%{q}%")))
        .order_by(Drug.code)
    )
    return ok(
        [
            {
                k: getattr(d, k)
                for k in (
                    "code",
                    "name",
                    "spec",
                    "default_frequency",
                    "contraindications",
                    "dose_min",
                    "dose_max",
                )
            }
            for d in rows
        ]
    )


def order_data(row):
    return {
        **{
            k: getattr(row, k)
            for k in (
                "id",
                "record_id",
                "doctor_id",
                "order_type",
                "content_json",
                "status",
                "validation_status",
                "validation_detail",
                "override_reason",
                "created_at",
            )
        },
        "patient_no": row.patient.patient_no,
    }


def checked(request, db, patient, items, record_id=None):
    result = validate_orders(db, patient.patient_no, items)
    if result["overall"] == "blocked":
        # Release any autoflushed record lock before the independent audit write.
        db.rollback()
        mark_audit(
            request,
            "medical_order.blocked",
            "emr_record",
            record_id,
            patient_id=patient.id,
            detail=result,
        )
        return JSONResponse(
            status_code=409,
            content={
                "code": 409,
                "message": "; ".join(
                    reason["message"]
                    for result_item in result["results"]
                    for reason in result_item["reasons"]
                    if reason["kind"] == "allergy"
                ),
                "data": result,
            },
        )
    return result


@router.post("/api/emr/orders/validate")
def validate(body: schema.OrderValidate, request: Request, db: DB, user: Writer):
    patient = visible_patient(db, user, body.patient_no)
    return ok(validate_orders(db, patient.patient_no, body.items))


@router.get("/api/emr/orders")
def orders(record_id: int, db: DB, user: CurrentUser):
    visible_record(db, user, record_id)
    return ok(
        [
            order_data(o)
            for o in db.scalars(
                select(MedicalOrder)
                .where(MedicalOrder.record_id == record_id)
                .order_by(MedicalOrder.id)
            )
        ]
    )


def assign_order(db, row, item, validation):
    content = item.model_dump(exclude={"order_type"})
    if item.order_type == "drug":
        content["drug_name"] = db.get(Drug, item.drug_code).name
    # The drug lookup can autoflush; assign the complete JSON so its name is persisted.
    row.order_type = item.order_type
    row.content_json = content
    row.validation_status = validation["status"]
    row.validation_detail = validation["reasons"]


@router.post("/api/emr/orders")
def create_orders(body: schema.OrderCreate, request: Request, db: DB, user: Writer):
    record = visible_record(db, user, body.record_id)
    unlocked(record)
    author_only(record, user)
    result = checked(request, db, record.patient, body.items, record.id)
    if isinstance(result, JSONResponse):
        return result
    rows = []
    for item, validation in zip(body.items, result["results"], strict=True):
        row = MedicalOrder(
            record_id=record.id,
            patient_id=record.patient_id,
            doctor_id=user.id,
            override_reason=body.override_reason,
        )
        assign_order(db, row, item, validation)
        db.add(row)
        rows.append(row)
    record.updated_at = now()  # Serialize order mutations against archiving.
    db.commit()
    mark_audit(
        request,
        "medical_order.create",
        "medical_order",
        rows[0].id,
        patient_id=record.patient_id,
        detail={
            "ids": [o.id for o in rows],
            "validation": result,
            "override_reason": body.override_reason,
        },
    )
    return ok([order_data(o) for o in rows])


def mutable_order(db, user, id):
    row = db.get(MedicalOrder, id)
    if row is None:
        raise HTTPException(404, "Order not found")
    record = visible_record(db, user, row.record_id)
    unlocked(record)
    author_only(record, user)
    if row.status == "stopped":
        raise HTTPException(409, "Order is already stopped")
    record.updated_at = now()
    return row


@router.patch("/api/emr/orders/{id}")
def modify_order(id: int, body: schema.OrderItem, request: Request, db: DB, user: Writer):
    row = mutable_order(db, user, id)
    result = checked(request, db, row.patient, [body], row.record_id)
    if isinstance(result, JSONResponse):
        return result
    assign_order(db, row, body, result["results"][0])
    db.commit()
    mark_audit(
        request,
        "medical_order.modify",
        "medical_order",
        id,
        patient_id=row.patient_id,
        detail=result,
    )
    return ok(order_data(row))


@router.post("/api/emr/orders/{id}/stop")
def stop_order(id: int, request: Request, db: DB, user: Writer):
    row = mutable_order(db, user, id)
    row.status = "stopped"
    db.commit()
    mark_audit(request, "medical_order.stop", "medical_order", id, patient_id=row.patient_id)
    return ok(order_data(row))
