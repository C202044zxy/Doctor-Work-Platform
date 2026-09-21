"""M1-07: the user directory, administrator CRUD, and the role dictionary.

`GET /api/users` is the one route here that any authenticated caller may read.
M5's invite picker used to own a private copy of exactly this projection
(`/api/meetings/doctors`, retired), and it existed only because the picker's
operator is a junior physician while this module's writes are administrator-only.
The three contact fields -- `email`, `status`, `created_at` -- are projected for
callers who hold `user.manage` and for nobody else; `response_model_exclude_none`
keeps them *absent* from everyone else's payload rather than present as `null`.

Reads are deliberately not department-scoped. Inviting a Neurology expert to a
Cardiology patient is the scenario the whole `temp_grant` mechanism exists for,
so a directory narrowed to the caller's own department would break M5's flow 2.
"""

from datetime import UTC
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app import user_contract as contract
from app.audit import mark_audit
from app.auth import CurrentUser, hash_password, ok, user_data
from app.dependencies import Pagination
from app.models import Department, Role, User
from app.security import ROLE_LABELS, allows, require_permission
from app.user_schemas import UserCreate, UserUpdate

router = APIRouter(tags=["Users"])

# Writes are administrator-only; the reads above them are not, which is why the
# gate is listed per route instead of on the router. `user.manage` already exists
# in the permission matrix, so no new permission name is introduced here.
MANAGE = [Depends(require_permission("user.manage"))]

DUPLICATE = "Username or email already registered"


def utc(value):
    """SQLite and MySQL drop the offset, so re-attach UTC before serializing.

    The contract types `created_at` as an offset-aware date-time, and SQLAlchemy
    hands back a naive datetime for a `DateTime(timezone=True)` column on both
    engines. Without this the administrator's list is a 500, not a wrong field.
    """
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def user_payload(user, *, full):
    """One directory row -- or, for an administrator, one management-table row.

    `full` is the caller's permission, not a route parameter: the contract puts
    the three contact fields on `User` with a description saying who may see
    them, because OpenAPI has no way to express a projection that depends on the
    caller's role.
    """
    payload = user_data(user)
    if full:
        payload.update(email=user.email, status=user.status, created_at=utc(user.created_at))
    return payload


def known_user(db, user_id):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    return user


def known_department(db, name):
    """A 422 rather than a 404: the name is part of the request body, not a route.

    This is `signup.py`'s rule and not `patients.department_id`'s. A 404 there
    means "that patient is outside your department scope" -- a T09 concept that
    has no meaning for the staff directory.
    """
    department = db.scalar(select(Department).where(Department.name == name))
    if department is None:
        raise HTTPException(422, f"Unknown department: {name}")
    return department.id


def known_role(db, title):
    role = db.scalar(select(Role).where(Role.name == title))
    if role is None:
        raise HTTPException(422, f"Unknown role: {title}")
    return role.id


@router.get(
    "/api/users",
    response_model=contract.UserListResponse,
    response_model_exclude_none=True,
)
def list_users(
    request: Request,
    user: CurrentUser,
    pagination: Annotated[Pagination, Depends()],
    q: Annotated[
        str | None,
        Query(description="姓名或账号的模糊匹配 / Substring of the name or the username"),
    ] = None,
    title: Annotated[
        contract.Role | None,
        Query(description="按角色精确筛选 / Exact role"),
    ] = None,
    department: Annotated[
        str | None,
        Query(description="按科室名精确筛选 / Exact department name"),
    ] = None,
    status: Annotated[
        contract.Status | None,
        Query(description="按账号状态精确筛选 / Exact account status"),
    ] = None,
):
    """用户目录 / The staff directory.

    Any authenticated caller, every department -- see the module docstring for
    why the T09 department scope is deliberately absent here. The result set is
    the account records the caller may see, not every column of them: `email`,
    `status` and `created_at` accompany the row only for an administrator.
    """
    with request.app.state.sessions() as db:
        conditions = []
        if q and q.strip():
            like = f"%{q.strip()}%"
            conditions.append(or_(User.name.like(like), User.username.like(like)))
        if title is not None:
            conditions.append(User.role_id.in_(select(Role.id).where(Role.name == title.value)))
        if department is not None:
            conditions.append(
                User.department_id.in_(select(Department.id).where(Department.name == department))
            )
        if status is not None:
            conditions.append(User.status == status.value)
        # `total` is the filtered whole, not the length of this page.
        total = db.scalar(select(func.count()).select_from(User).where(*conditions)) or 0
        rows = db.scalars(
            select(User)
            .where(*conditions)
            # `id` is not decoration: without a total order a row can appear on
            # two pages, or on none, as the offset advances.
            .order_by(User.name, User.id)
            .offset(pagination.offset)
            .limit(pagination.size)
        )
        full = allows(user, "user.manage")
        return ok(
            {
                "items": [user_payload(row, full=full) for row in rows],
                "total": total,
                "page": pagination.page,
                "size": pagination.size,
            }
        )


@router.get(
    "/api/users/{id}",
    response_model=contract.UserResponse,
    response_model_exclude_none=True,
    dependencies=MANAGE,
)
def get_user(request: Request, user: CurrentUser, id: int):
    """用户详情 / One account, in full.

    Administrator-only, unlike the list. The detail shape carries the contact
    fields unconditionally so it has a single form, which is only honest while
    it stays behind `user.manage`; opening it up would mean a second,
    caller-dependent projection on the same route.
    """
    with request.app.state.sessions() as db:
        return ok(user_payload(known_user(db, id), full=True))


@router.post(
    "/api/users",
    response_model=contract.UserResponse,
    dependencies=MANAGE,
)
def create_user(request: Request, user: CurrentUser, body: UserCreate):
    """创建用户 / Create an account.

    Answers 200, not 201 -- the contract says so and the client reads the
    envelope, not the status line. `status` is not accepted: a new account is
    `active`, which is the model's default.
    """
    with request.app.state.sessions() as db:
        # Both unique columns are pre-checked. `users.email` is unique too, so a
        # check on the username alone would turn a duplicate email into a 500.
        clash = db.scalar(
            select(User.id).where(
                or_(
                    func.lower(User.username) == body.username.lower(),
                    func.lower(User.email) == body.email.lower(),
                )
            )
        )
        if clash is not None:
            raise HTTPException(409, DUPLICATE)
        created = User(
            username=body.username,
            name=body.name,
            email=body.email,
            password_hash=hash_password(body.password),
            role_id=known_role(db, body.title.value),
            department_id=known_department(db, body.department),
        )
        db.add(created)
        try:
            db.commit()
        except IntegrityError:
            # The pre-check is not a lock; the unique index is the real guard.
            db.rollback()
            raise HTTPException(409, DUPLICATE) from None
        mark_audit(
            request,
            "user.create",
            "user",
            created.id,
            detail={
                "username": created.username,
                "title": body.title.value,
                "department": body.department,
            },
        )
        return ok(user_payload(created, full=True))


@router.patch(
    "/api/users/{id}",
    response_model=contract.UserResponse,
    dependencies=MANAGE,
)
def update_user(request: Request, user: CurrentUser, id: int, body: UserUpdate):
    """修改用户 / Edit an account.

    `title`, `department`, `name`, `status` are all optional. An empty body is a
    no-op that still answers 200 -- and still writes an audit row, because the
    request happened. An explicit `null` on any of the four is a 422 naming the
    field: they all sit on non-null columns, so accepting the null would be a 500
    two frames later.

    Setting `status` to `disabled` refuses that account's already-issued tokens
    from its next request on; `app.auth.current_user` reads the live row rather
    than trusting the claims, and this route is the first place that rule becomes
    reachable from the UI.
    """
    with request.app.state.sessions() as db:
        target = known_user(db, id)
        for field in ("name", "title", "department", "status"):
            if field in body.model_fields_set and getattr(body, field) is None:
                raise HTTPException(422, f"{field} must not be null")
        # Resolve before mutating, so an unknown department or role cannot leave
        # the row half-edited even for the instant before the rollback.
        role_id = known_role(db, body.title.value) if body.title is not None else None
        department_id = (
            known_department(db, body.department) if body.department is not None else None
        )
        changed = []
        if body.name is not None:
            target.name = body.name
            changed.append("name")
        if role_id is not None:
            target.role_id = role_id
            changed.append("title")
        if department_id is not None:
            target.department_id = department_id
            changed.append("department")
        if body.status is not None:
            target.status = body.status.value
            changed.append("status")
        db.commit()
        mark_audit(
            request,
            "user.update",
            "user",
            target.id,
            # Field names only. A password never reaches this route, and nothing
            # else about the row is worth copying into the log.
            detail={"username": target.username, "changed": changed},
        )
        return ok(user_payload(target, full=True))


@router.get("/api/roles", response_model=contract.RoleListResponse)
def list_roles(user: CurrentUser):
    """角色字典 / The role dictionary.

    Readable by anyone signed in: the client needs the display names to render a
    `title` it already holds, and the codes are not a secret. `ROLE_LABELS` is
    keyed by the same strings as `PERMISSIONS`, which is what makes the three
    entries the complete set rather than a list someone has to keep in step.
    """
    return ok([{"code": code, "label": label} for code, label in ROLE_LABELS.items()])
