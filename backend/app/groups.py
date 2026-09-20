"""T17: patient groups -- create, rename, add and remove members, delete.

A group is a manual grouping inside one department: by condition, by management
status, or by hand. Three decisions are worth stating.

* **A group belongs to one department.** That is what makes T17 scenario S2
  meaningful: a caller never sees a group from another department, so a group
  cannot be used to widen the T09 scope, and the members a group filter returns
  are always patients the caller could already read.
* **A member must be in the group's department.** Otherwise an `admin` could
  park a Cardiology patient in an IT group and hand it to a Cardiology junior
  through the filter. Enforced as a 422, because the request is understood and
  the *membership* is what is wrong.
* **Deleting a group never deletes a patient.** The membership rows go; the
  people stay in the directory. T17 scenario S2 checks exactly that.

Every write marks an audit entry (`patient_group.*`), including the membership
changes, so the trail says who put whom into which group.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.audit import mark_audit
from app.auth import CurrentUser, ok
from app.models import Patient, PatientGroup, PatientGroupMember, User
from app.patients import department_id, patient_scope
from app.schemas import (
    GroupMembersRequest,
    PatientGroupCreate,
    PatientGroupListResponse,
    PatientGroupRead,
    PatientGroupResponse,
    PatientGroupUpdate,
)
from app.security import allows, require_permission

router = APIRouter()

# T17 is a clinical write like any other: every signed-in role holds
# `patient.write`, and the day a read-only role appears it is refused here.
WRITE = [Depends(require_permission("patient.write"))]


def acting_user(request: Request, user: CurrentUser):
    """Name the actor for the audit middleware, which reads request.state.identity."""
    request.state.identity = user
    return user


Actor = Annotated[User, Depends(acting_user)]


def group_scope(user):
    """True for `data.all`, otherwise the caller's own department."""
    if allows(user, "data.all"):
        return True
    return PatientGroup.department_id == user.department_id


def _member_counts(db, group_ids: list[int]) -> dict[int, int]:
    """Members per group for the groups in hand, in one query.

    Soft-deleted patients are not counted: the count has to agree with what the
    group filter returns, and that filter only ever returns live patients.
    """
    found: dict[int, int] = {}
    if not group_ids:
        return found
    rows = db.execute(
        select(PatientGroupMember.group_id, func.count(PatientGroupMember.id))
        .join(Patient, PatientGroupMember.patient_id == Patient.id)
        .where(PatientGroupMember.group_id.in_(group_ids), Patient.deleted_at.is_(None))
        .group_by(PatientGroupMember.group_id)
    ).all()
    for group_id, count in rows:
        found[group_id] = count
    return found


def _read(group: PatientGroup, member_count: int) -> PatientGroupRead:
    return PatientGroupRead(
        id=group.id,
        name=group.name,
        description=group.description or "",
        member_count=member_count,
    )


def _visible_group(db, user, group_id: int) -> PatientGroup:
    """A group outside the caller's department is a 404, like every other scope."""
    group = db.scalar(select(PatientGroup).where(PatientGroup.id == group_id, group_scope(user)))
    if group is None:
        raise HTTPException(404, "Patient group not found")
    return group


def _members_of(db, group: PatientGroup, patient_nos: list[str]) -> list[Patient]:
    """The named patients: unknown numbers and ones outside the caller's scope are a
    404, and one belonging to another department than the group is a 422 naming it.
    """
    found = {
        patient.patient_no: patient
        for patient in db.scalars(
            select(Patient).where(
                Patient.patient_no.in_(patient_nos),
                Patient.deleted_at.is_(None),
                patient_scope(db.info["user"]),
            )
        )
    }
    missing = sorted({no for no in patient_nos if no not in found})
    if missing:
        raise HTTPException(404, "Patient not found: " + ", ".join(missing))
    elsewhere = sorted(
        patient.patient_no
        for patient in found.values()
        if patient.department_id != group.department_id
    )
    if elsewhere:
        raise HTTPException(
            422, "Patient is not in the group's department: " + ", ".join(elsewhere)
        )
    return [found[no] for no in patient_nos]


def groups_for_patient(db, patient: Patient) -> list[PatientGroupRead]:
    """The groups a patient is in, for `PatientDetail.groups`.

    `patient.department_id` bounds the lookup, so a detail read can never list a
    group the caller is not allowed to know about.
    """
    rows = list(
        db.scalars(
            select(PatientGroup)
            .join(PatientGroupMember, PatientGroupMember.group_id == PatientGroup.id)
            .where(
                PatientGroupMember.patient_id == patient.id,
                PatientGroup.department_id == patient.department_id,
            )
            .order_by(PatientGroup.name, PatientGroup.id)
        )
    )
    counts = _member_counts(db, [row.id for row in rows])
    return [_read(row, counts.get(row.id, 0)) for row in rows]


def _already_in(db, group: PatientGroup, patient_ids: list[int]) -> set[str]:
    """The patient numbers from `patient_ids` that are already members."""
    if not patient_ids:
        return set()
    return set(
        db.scalars(
            select(Patient.patient_no)
            .join(PatientGroupMember, PatientGroupMember.patient_id == Patient.id)
            .where(
                PatientGroupMember.group_id == group.id,
                PatientGroupMember.patient_id.in_(patient_ids),
            )
        )
    )


@router.get("/api/patient-groups", response_model=PatientGroupListResponse)
def list_patient_groups(request: Request, user: Actor):
    """分组列表 / List the groups in scope, with member counts."""
    with request.app.state.sessions() as db:
        db.info["user"] = user
        rows = list(
            db.scalars(
                select(PatientGroup)
                .where(group_scope(user))
                .order_by(PatientGroup.name, PatientGroup.id)
            )
        )
        counts = _member_counts(db, [row.id for row in rows])
        return ok([_read(row, counts.get(row.id, 0)) for row in rows])


@router.post("/api/patient-groups", response_model=PatientGroupResponse, dependencies=WRITE)
def create_patient_group(request: Request, user: Actor, body: PatientGroupCreate):
    """新建分组 / Create a group.

    The department defaults to the caller's own and naming another one is a 403
    without `data.all` -- the same rule patient creation uses, through the same
    helper. A name already used in that department is a 409.
    """
    with request.app.state.sessions() as db:
        db.info["user"] = user
        owner = department_id(db, user, body.department or user.department.name)
        clash = db.scalar(
            select(PatientGroup).where(
                PatientGroup.department_id == owner, PatientGroup.name == body.name
            )
        )
        if clash is not None:
            raise HTTPException(409, f"A group named {body.name} already exists here")
        group = PatientGroup(
            name=body.name,
            description=body.description,
            department_id=owner,
            created_by=user.id,
        )
        db.add(group)
        try:
            db.commit()
        except IntegrityError:
            # A concurrent create claimed the name between the check and the insert.
            db.rollback()
            raise HTTPException(409, f"A group named {body.name} already exists here") from None
        db.refresh(group)
        mark_audit(
            request, "patient_group.create", "patient_group", group.id, detail={"name": group.name}
        )
        return ok(_read(group, 0))


@router.patch(
    "/api/patient-groups/{group_id}",
    response_model=PatientGroupResponse,
    dependencies=WRITE,
)
def update_patient_group(request: Request, user: Actor, group_id: int, body: PatientGroupUpdate):
    """重命名分组 / Rename a group or edit its description."""
    with request.app.state.sessions() as db:
        db.info["user"] = user
        group = _visible_group(db, user, group_id)
        if "name" in body.model_fields_set and body.name is None:
            raise HTTPException(422, "name must not be null")
        updates = body.model_dump(exclude_unset=True)
        if updates.get("name") and updates["name"] != group.name:
            clash = db.scalar(
                select(PatientGroup).where(
                    PatientGroup.department_id == group.department_id,
                    PatientGroup.name == updates["name"],
                )
            )
            if clash is not None:
                raise HTTPException(409, f"A group named {updates['name']} already exists here")
        for field, value in updates.items():
            setattr(group, field, value)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "That group name is already taken here") from None
        db.refresh(group)
        mark_audit(
            request,
            "patient_group.update",
            "patient_group",
            group.id,
            detail={"name": group.name},
        )
        counts = _member_counts(db, [group.id])
        return ok(_read(group, counts.get(group.id, 0)))


@router.delete(
    "/api/patient-groups/{group_id}",
    response_model=PatientGroupResponse,
    dependencies=WRITE,
)
def delete_patient_group(request: Request, user: Actor, group_id: int):
    """删除分组 / Delete the grouping, never the patients."""
    with request.app.state.sessions() as db:
        db.info["user"] = user
        group = _visible_group(db, user, group_id)
        payload = _read(group, _member_counts(db, [group.id]).get(group.id, 0))
        db.execute(delete(PatientGroupMember).where(PatientGroupMember.group_id == group.id))
        db.delete(group)
        db.commit()
        mark_audit(
            request,
            "patient_group.delete",
            "patient_group",
            group_id,
            detail={"name": payload.name, "patients_kept": payload.member_count},
        )
        return ok(payload)


@router.post(
    "/api/patient-groups/{group_id}/members",
    response_model=PatientGroupResponse,
    dependencies=WRITE,
)
def add_patient_group_members(
    request: Request, user: Actor, group_id: int, body: GroupMembersRequest
):
    """批量加成员 / Add patients to a group.

    A patient already in the group is a 409 naming them (T17 scenario S1). The
    check is done before the insert so the message is specific, and the unique
    constraint is what makes a concurrent double-add impossible rather than
    merely unlikely.
    """
    with request.app.state.sessions() as db:
        db.info["user"] = user
        group = _visible_group(db, user, group_id)
        patients = _members_of(db, group, body.patient_nos)
        existing = _already_in(db, group, [patient.id for patient in patients])
        if existing:
            raise HTTPException(409, "Already in this group: " + ", ".join(sorted(existing)))
        db.add_all(
            PatientGroupMember(group_id=group.id, patient_id=patient.id) for patient in patients
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Already in this group") from None
        mark_audit(
            request,
            "patient_group.members.add",
            "patient_group",
            group.id,
            detail={"patient_nos": [patient.patient_no for patient in patients]},
        )
        counts = _member_counts(db, [group.id])
        return ok(_read(group, counts.get(group.id, 0)))


@router.delete(
    "/api/patient-groups/{group_id}/members",
    response_model=PatientGroupResponse,
    dependencies=WRITE,
)
def remove_patient_group_members(
    request: Request, user: Actor, group_id: int, body: GroupMembersRequest
):
    """批量移出分组 / Remove patients from a group.

    Removing someone who is not in the group is a 404 naming them: the grouping
    is what the caller asked to change, and silently answering 200 would leave
    the screen showing a state the database does not have.
    """
    with request.app.state.sessions() as db:
        db.info["user"] = user
        group = _visible_group(db, user, group_id)
        patients = _members_of(db, group, body.patient_nos)
        present = _already_in(db, group, [patient.id for patient in patients])
        absent = sorted({no for no in body.patient_nos if no not in present})
        if absent:
            raise HTTPException(404, "Not in this group: " + ", ".join(absent))
        db.execute(
            delete(PatientGroupMember).where(
                PatientGroupMember.group_id == group.id,
                PatientGroupMember.patient_id.in_([patient.id for patient in patients]),
            )
        )
        db.commit()
        mark_audit(
            request,
            "patient_group.members.remove",
            "patient_group",
            group.id,
            detail={"patient_nos": [patient.patient_no for patient in patients]},
        )
        counts = _member_counts(db, [group.id])
        return ok(_read(group, counts.get(group.id, 0)))
