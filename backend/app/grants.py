"""T10 patient-scoped grants and the T09 data-scope integration hook."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import AwareDatetime, Field
from sqlalchemy import exists, func, or_, select, update

from app import auth_schemas as contract
from app.auth import CurrentUser, ok
from app.models import AuditLog, Patient, TempGrant, User

router = APIRouter()


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def patient_scope(user):
    if user.role.name == "admin":
        return True
    return or_(
        Patient.department_id == user.department_id,
        exists().where(
            TempGrant.patient_id == Patient.id,
            TempGrant.grantee_id == user.id,
            TempGrant.is_valid.is_(True),
            TempGrant.expire_at > datetime.now(UTC),
        ),
    )


def require_grant_manager(user):
    if user.role.name not in {"admin", "senior"}:
        raise HTTPException(403, "Only admin or senior may manage grants")


def grant_data(grant):
    return {
        "id": grant.id,
        "grantee_id": grant.grantee_id,
        "grantee_name": grant.grantee.name,
        "patient_no": grant.patient.patient_no,
        "reason": grant.reason,
        "granted_by": grant.granted_by,
        "expire_at": utc(grant.expire_at),
        "is_valid": grant.is_valid and utc(grant.expire_at) > datetime.now(UTC),
        "created_at": utc(grant.created_at),
    }


def audit_grant(db, grant, action, actor_id=None):
    db.add(
        AuditLog(
            action=action,
            patient_id=grant.patient_id,
            detail={"grant_id": grant.id, "grantee_id": grant.grantee_id, "user_id": actor_id},
        )
    )


def expire_grants(sessions):
    """Each worker scans; a conditional UPDATE claims each row atomically.

    Only its winning transaction writes the audit event, so concurrent workers do
    not duplicate expiry events. Access checks also test time, independent of scans.
    """
    now = datetime.now(UTC)
    with sessions() as db:
        ids = list(
            db.scalars(
                select(TempGrant.id).where(TempGrant.is_valid.is_(True), TempGrant.expire_at <= now)
            )
        )
        for grant_id in ids:
            changed = db.execute(
                update(TempGrant)
                .where(
                    TempGrant.id == grant_id,
                    TempGrant.is_valid.is_(True),
                    TempGrant.expire_at <= now,
                )
                .values(is_valid=False)
            ).rowcount
            if changed:
                audit_grant(db, db.get(TempGrant, grant_id), "temp_grant.expire")
        db.commit()


class TempGrantCreateRequest(contract.TempGrantCreateRequest):
    grantee_id: int = Field(gt=0)
    patient_no: str = Field(min_length=1, max_length=20)
    reason: str = Field(min_length=1, max_length=500)
    expire_at: AwareDatetime


def managed_patient(db, user, patient_id):
    # A senior can delegate only their own department, not re-delegate a grant.
    patient = db.get(Patient, patient_id)
    if patient is None or patient.deleted_at is not None:
        raise HTTPException(404, "Patient not found")
    if user.role.name != "admin" and patient.department_id != user.department_id:
        raise HTTPException(404, "Patient not found")
    return patient


@router.post("/api/temp-grants", response_model=contract.TempGrantResponse)
def create_grant(body: TempGrantCreateRequest, request: Request, user: CurrentUser):
    require_grant_manager(user)
    if body.expire_at <= datetime.now(UTC) or not body.reason.strip():
        raise HTTPException(422, "A future expire_at and nonblank reason are required")
    with request.app.state.sessions() as db:
        patient = db.scalar(select(Patient).where(Patient.patient_no == body.patient_no))
        if patient is None:
            raise HTTPException(404, "Patient not found")
        managed_patient(db, user, patient.id)
        grantee = db.get(User, body.grantee_id)
        if grantee is None or grantee.status != "active":
            raise HTTPException(404, "Active grantee not found")
        grant = TempGrant(
            grantee_id=grantee.id,
            patient_id=patient.id,
            reason=body.reason.strip(),
            granted_by=user.id,
            expire_at=body.expire_at.astimezone(UTC),
        )
        db.add(grant)
        db.flush()
        audit_grant(db, grant, "temp_grant.create", user.id)
        db.commit()
        db.refresh(grant)
        return ok(grant_data(grant))


@router.get("/api/temp-grants", response_model=contract.TempGrantListResponse)
def list_grants(
    request: Request,
    user: CurrentUser,
    grantee_id: int | None = None,
    patient_no: str | None = None,
    is_valid: bool | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    require_grant_manager(user)
    with request.app.state.sessions() as db:
        conditions = []
        if user.role.name != "admin":
            conditions.append(Patient.department_id == user.department_id)
        if grantee_id is not None:
            conditions.append(TempGrant.grantee_id == grantee_id)
        if patient_no is not None:
            conditions.append(Patient.patient_no == patient_no)
        live = TempGrant.is_valid.is_(True) & (TempGrant.expire_at > datetime.now(UTC))
        if is_valid is not None:
            conditions.append(live if is_valid else ~live)
        query = (
            select(TempGrant).join(Patient, TempGrant.patient_id == Patient.id).where(*conditions)
        )
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = db.scalars(query.order_by(TempGrant.id.desc()).offset((page - 1) * size).limit(size))
        return ok(
            {"items": [grant_data(row) for row in rows], "total": total, "page": page, "size": size}
        )


@router.delete("/api/temp-grants/{id}", response_model=contract.TempGrantResponse)
def revoke_grant(id: int, request: Request, user: CurrentUser):
    require_grant_manager(user)
    with request.app.state.sessions() as db:
        grant = db.get(TempGrant, id)
        if grant is None:
            raise HTTPException(404, "Grant not found")
        managed_patient(db, user, grant.patient_id)
        changed = db.execute(
            update(TempGrant)
            .where(TempGrant.id == id, TempGrant.is_valid.is_(True))
            .values(is_valid=False)
        ).rowcount
        if changed:
            audit_grant(db, grant, "temp_grant.revoke", user.id)
        db.commit()
        db.refresh(grant)
        return ok(grant_data(grant))
