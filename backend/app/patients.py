"""T09: all patient selection and counting share this SQL scope."""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import exists, or_, select

from app.models import Patient, TempGrant
from app.security import allows


def temporary_grant_condition(user):
    return exists().where(
        TempGrant.patient_id == Patient.id,
        TempGrant.grantee_id == user.id,
        TempGrant.is_valid.is_(True),
        TempGrant.expire_at > datetime.now(UTC),
    )


def patient_scope(user):
    if allows(user, "data.all"):
        return True
    return or_(Patient.department_id == user.department_id, temporary_grant_condition(user))


def visible_patient(db, user, patient_no):
    patient = db.scalar(
        select(Patient).where(
            Patient.patient_no == patient_no, Patient.deleted_at.is_(None), patient_scope(user)
        )
    )
    if patient is None:
        raise HTTPException(404, "Patient not found")
    return patient
