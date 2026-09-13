"""Shared B route dependencies and response helpers."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.models import Patient
from app.patients import patient_scope, visible_patient


def get_db(request: Request, user: CurrentUser):
    with request.app.state.sessions() as db:
        db.info.update(user=user, request=request)
        yield db


DB = Annotated[Session, Depends(get_db)]


def ok(data):
    return {"code": 0, "message": "ok", "data": data}


def utc(value):
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


def fields(row, *names):
    return {
        name: utc(getattr(row, name))
        if isinstance(getattr(row, name), datetime)
        else getattr(row, name)
        for name in names
    }


def patient_for(db, patient_id):
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(404, "Patient not found")
    return visible_patient(db, db.info["user"], patient.patient_no)


def scoped(model, db):
    return (
        select(model)
        .join(Patient, model.patient_id == Patient.id)
        .where(Patient.deleted_at.is_(None), patient_scope(db.info["user"]))
    )


def page(db, stmt, pagination, render):
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.offset(pagination.offset).limit(pagination.size)).all()
    return {
        "items": [render(row) for row in rows],
        "total": total,
        "page": pagination.page,
        "size": pagination.size,
    }
