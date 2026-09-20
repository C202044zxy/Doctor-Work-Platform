"""T09: every patient selection, and the department rule that guards a write."""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import exists, or_, select

from app.models import Department, Patient, TempGrant
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


def department_id(db, user, name: str) -> int:
    """Resolve a department name for a write, under the T09 department rule.

    Shared by patient writes and patient-group writes so the two cannot answer
    "may I act in this department?" differently: an unknown name is a 404, and
    naming a department that is not the caller's is a 403 unless the role carries
    `data.all`.
    """
    department = db.scalar(select(Department).where(Department.name == name))
    if department is None:
        raise HTTPException(404, f"Department not found: {name}")
    if not allows(user, "data.all") and department.id != user.department_id:
        raise HTTPException(403, "Cannot write patients in another department")
    return department.id


def visible_patient(db, user, patient_no):
    patient = db.scalar(
        select(Patient).where(
            Patient.patient_no == patient_no, Patient.deleted_at.is_(None), patient_scope(user)
        )
    )
    if patient is None:
        raise HTTPException(404, "Patient not found")
    return patient
