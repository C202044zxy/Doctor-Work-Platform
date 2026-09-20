"""T20 APIs. A installs record loader and validator through app.state.

order_record_loader(db, record_id) -> object with patient_id and status; None = 404.
order_validator(db, patient_id, list[dict]) -> {overall, results:[{index,status,reasons}]}.
Both are invoked within the order transaction. No fallback can pass an unchecked drug.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.audit import mark_audit
from app.security import require_permission
from app.work_common import DB, fields, ok, patient_for
from app.work_models import MedicalOrder
from app.work_schemas import Envelope, OrderCreate, OrderItem, OrderRead, ValidationRead

router = APIRouter(tags=["EMR"], dependencies=[Depends(require_permission("emr.write"))])


def record_for(db, record_id, *, write=False):
    loader = getattr(db.info["request"].app.state, "order_record_loader", None)
    if loader is None:
        raise HTTPException(503, "T19 record integration is not installed")
    record = loader(db, record_id)
    if record is None:
        raise HTTPException(404, "Record not found")
    patient = patient_for(db, record.patient_id)
    if write and record.status == "archived":
        raise HTTPException(409, "Archived records are read-only")
    return patient


def validate(db, patient_id, items):
    validator = getattr(db.info["request"].app.state, "order_validator", None)
    if validator is None:
        raise HTTPException(503, "T21 order validation engine is not installed")
    data = validator(db, patient_id, [item.model_dump() for item in items])
    results = data.get("results", [])
    if (
        len(results) != len(items)
        or {r.get("index") for r in results} != set(range(len(items)))
        or any(
            r.get("status") not in {"passed", "warning", "blocked"}
            or not isinstance(r.get("reasons"), list)
            for r in results
        )
    ):
        raise HTTPException(503, "Invalid T21 validation result")
    try:
        for result in results:
            ValidationRead.model_validate(result)
    except ValidationError:
        raise HTTPException(503, "Invalid T21 validation detail") from None
    if any(r["status"] == "blocked" for r in results):
        mark_audit(
            db.info["request"], "medical_order.blocked", "medical_order", patient_id=patient_id
        )
        raise HTTPException(
            409,
            next(
                (
                    reason.get("message")
                    for r in results
                    if r["status"] == "blocked"
                    for reason in r["reasons"]
                    if reason.get("message")
                ),
                "Order blocked by validation",
            ),
        )
    return {r["index"]: r for r in results}


def order_data(db, row):
    patient = patient_for(db, row.patient_id)
    return {
        **fields(
            row,
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
        ),
        "patient_no": patient.patient_no,
        "validation_result": {"status": row.validation_status, "reasons": row.validation_detail},
    }


@router.get("/api/legacy/emr/orders", response_model=Envelope[list[OrderRead]])
def list_orders(record_id: int, db: DB):
    record_for(db, record_id)
    mark_audit(db.info["request"], "medical_order.view", "medical_record", record_id)
    return ok(
        [
            order_data(db, row)
            for row in db.scalars(
                select(MedicalOrder)
                .where(MedicalOrder.record_id == record_id)
                .order_by(MedicalOrder.id)
            )
        ]
    )


@router.post("/api/legacy/emr/orders", response_model=Envelope[list[OrderRead]])
def create_orders(body: OrderCreate, db: DB):
    patient = record_for(db, body.record_id, write=True)
    results = validate(db, patient.id, body.items)
    rows = []
    for index, item in enumerate(body.items):
        row = MedicalOrder(
            record_id=body.record_id,
            patient_id=patient.id,
            doctor_id=db.info["user"].id,
            order_type=item.order_type,
            content_json=item.model_dump(exclude={"order_type"}),
            validation_status=results[index]["status"],
            validation_detail=results[index]["reasons"],
            override_reason=body.override_reason,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    mark_audit(
        db.info["request"],
        "medical_order.create",
        "medical_record",
        body.record_id,
        patient_id=patient.id,
        detail={"order_ids": [r.id for r in rows]},
    )
    db.commit()
    return ok([order_data(db, row) for row in rows])


def editable_order(db, id):
    row = db.get(MedicalOrder, id)
    if row is None:
        raise HTTPException(404, "Order not found")
    record_for(db, row.record_id, write=True)
    if row.status != "active":
        raise HTTPException(409, "Stopped orders are read-only")
    return row


@router.patch("/api/legacy/emr/orders/{id}", response_model=Envelope[OrderRead])
def update_order(id: int, body: OrderItem, db: DB):
    row = editable_order(db, id)
    result = validate(db, row.patient_id, [body])[0]
    row.content_json = body.model_dump(exclude={"order_type"})
    row.order_type, row.validation_status, row.validation_detail = (
        body.order_type,
        result["status"],
        result["reasons"],
    )
    mark_audit(
        db.info["request"], "medical_order.modify", "medical_order", id, patient_id=row.patient_id
    )
    db.commit()
    return ok(order_data(db, row))


@router.post("/api/legacy/emr/orders/{id}/stop", response_model=Envelope[OrderRead])
def stop_order(id: int, db: DB):
    row = editable_order(db, id)
    row.status = "stopped"
    mark_audit(
        db.info["request"], "medical_order.stop", "medical_order", id, patient_id=row.patient_id
    )
    db.commit()
    return ok(order_data(db, row))
