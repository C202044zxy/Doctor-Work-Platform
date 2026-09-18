from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Annotated

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import case, func, or_, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import auth, auth_schemas, crypto, face_login, grants, meetings, signup
from app.allergies import allergen_name, dictionary, get_patient_allergens
from app.audit import audit_request, mark_audit
from app.audit_export import audit_csv, content_disposition, filename_range
from app.config import Settings
from app.database import make_engine, session_factory
from app.dependencies import Pagination
from app.models import Allergy, AuditLog, Department, Patient
from app.patients import patient_scope, visible_patient
from app.schemas import (
    AllergenDictionaryResponse,
    AllergenRead,
    AllergyCreate,
    AllergyListResponse,
    AllergyRead,
    AllergyResponse,
    AllergyUpdate,
    AuditLogListData,
    AuditLogListResponse,
    AuditLogRead,
    DepartmentListResponse,
    DepartmentRead,
    ErrorResponse,
    OkData,
    OkResponse,
    PatientCreate,
    PatientDetail,
    PatientListData,
    PatientListResponse,
    PatientResponse,
    PatientSummary,
    PatientUpdate,
    join_tags,
    split_tags,
)
from app.security import ProtectedFastAPI, allows, require_permission

PATIENT_NO_RETRIES = 5


def get_session(request: Request, user: auth.CurrentUser):
    request.state.identity = user
    with request.app.state.sessions() as session:
        session.info["user"] = user
        session.info["request"] = request
        yield session


DB = Annotated[Session, Depends(get_session)]


def _ok(data):
    """The contract envelope: {code, message, data}, with code 0 for success."""
    return {"code": 0, "message": "ok", "data": data}


def _as_utc(value: datetime) -> datetime:
    """SQLite and MySQL drop the offset, so re-attach UTC before serializing."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _masked_identifiers(patient: Patient) -> tuple[str | None, str | None]:
    """Decrypt the identifiers only long enough to mask them."""
    phone = crypto.mask_phone(crypto.decrypt(patient.phone_enc)) if patient.phone_enc else None
    id_card = (
        crypto.mask_id_card(crypto.decrypt(patient.id_card_enc)) if patient.id_card_enc else None
    )
    return phone, id_card


def _summary(patient: Patient, allergy_count: int = 0, has_severe: bool = False) -> PatientSummary:
    phone, _ = _masked_identifiers(patient)
    return PatientSummary(
        patient_no=patient.patient_no,
        name=patient.name,
        gender=patient.gender,
        birth_date=patient.birth_date,
        phone_masked=phone,
        phone=phone,
        department=patient.department.name,
        symptom_tags=split_tags(patient.symptom_tags),
        allergy_count=allergy_count,
        has_severe_allergy=has_severe,
        admitted_at=patient.admitted_at,
        notes=patient.notes,
        created_at=_as_utc(patient.created_at),
    )


def _detail(
    patient: Patient, allergies: list[Allergy], allergy_count: int, has_severe: bool
) -> PatientDetail:
    _, id_card = _masked_identifiers(patient)
    return PatientDetail(
        **_summary(patient, allergy_count, has_severe).model_dump(),
        id_card_masked=id_card,
        id_card=id_card,
        allergies=[AllergyRead.model_validate(item, from_attributes=True) for item in allergies],
        histories=[],
        groups=[],
    )


def _severity_summary(allergies: list[Allergy]) -> tuple[int, bool]:
    return len(allergies), any(item.severity == "severe" for item in allergies)


def _allergy_stats(db: Session, patient_ids: list[int]) -> dict[int, tuple[int, bool]]:
    """One grouped query for a page of patients, so the list stays free of N+1 reads."""
    if not patient_ids:
        return {}
    rows = db.execute(
        select(
            Allergy.patient_id,
            func.count(Allergy.id),
            func.max(case((Allergy.severity == "severe", 1), else_=0)),
        )
        .where(Allergy.patient_id.in_(patient_ids))
        .group_by(Allergy.patient_id)
    ).all()
    return {patient_id: (count, bool(severe)) for patient_id, count, severe in rows}


def _next_patient_no(db: Session) -> str:
    """Return the next free P<year><sequence> number, for example P20260001."""
    prefix = f"P{datetime.now(UTC).year}"
    latest = db.scalar(
        select(func.max(Patient.patient_no)).where(Patient.patient_no.like(f"{prefix}%"))
    )
    tail = latest.removeprefix(prefix) if latest else ""
    sequence = int(tail) + 1 if tail.isdigit() else 1
    return f"{prefix}{sequence:04d}"


def _live_patient(db: Session, patient_no: str) -> Patient:
    return visible_patient(db, db.info["user"], patient_no)


def _department_id(db: Session, name: str) -> int:
    department = db.scalar(select(Department).where(Department.name == name))
    if department is None:
        raise HTTPException(404, f"Department not found: {name}")
    user = db.info["user"]
    if not allows(user, "data.all") and department.id != user.department_id:
        raise HTTPException(403, "Cannot write patients in another department")
    return department.id


def _audit(db: Session, action: str, patient_id: int, detail: dict | None = None) -> None:
    request = db.info["request"]
    patient = db.get(Patient, patient_id)
    kind = action.split(".")[0]
    oid = str(detail["id"]) if detail and "id" in detail else patient.patient_no
    mark_audit(request, action, kind, oid, patient_id=patient_id, detail=detail)


class AuditFilters:
    """T12's four query conditions, declared once for both endpoints.

    `GET /api/audit-logs` and `GET /api/audit-logs/export` take exactly the same
    filters. Declaring them here rather than typing the parameter list out twice is
    the same move as `Pagination`, and it is what makes criterion 2's "the export
    agrees with the list" a property of the code instead of a promise about two
    copies that agree today.
    """

    def __init__(
        self,
        user_id: Annotated[int | None, Query(description="操作者主键 / Acting user id")] = None,
        action: Annotated[
            str, Query(max_length=50, description="动作精确匹配 / Exact action key")
        ] = "",
        object_type: Annotated[
            str, Query(max_length=50, description="对象类型精确匹配 / Exact object type")
        ] = "",
        # `from` is a Python keyword, so the parameter carries the alias instead.
        from_: Annotated[
            datetime | None,
            Query(alias="from", description="写入时间起（含）/ Written at or after"),
        ] = None,
        to: Annotated[
            datetime | None, Query(description="写入时间止（含）/ Written at or before")
        ] = None,
    ):
        self.user_id = user_id or None
        self.action = action
        self.object_type = object_type
        self.from_ = from_
        self.to = to

    def conditions(self):
        conditions = []
        if self.user_id is not None:
            conditions.append(AuditLog.user_id == self.user_id)
        if self.action:
            conditions.append(AuditLog.action == self.action)
        if self.object_type:
            conditions.append(AuditLog.object_type == self.object_type)
        if self.from_ is not None:
            conditions.append(AuditLog.created_at >= self.from_)
        if self.to is not None:
            conditions.append(AuditLog.created_at <= self.to)
        return conditions


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    crypto.configure(settings.patient_data_key)
    engine = make_engine(settings.database_url)
    cache = (
        Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
        if settings.redis_url
        else None
    )

    @asynccontextmanager
    async def lifespan(app):
        scheduler = BackgroundScheduler(timezone="UTC")
        if settings.scheduler_enabled:
            scheduler.add_job(
                grants.expire_grants,
                "interval",
                minutes=1,
                args=[app.state.sessions],
                id="expire_temp_grants",
                max_instances=1,
                coalesce=True,
            )
            scheduler.start()
        app.state.scheduler = scheduler
        try:
            yield
        finally:
            if scheduler.running:
                scheduler.shutdown(wait=True)
            if cache:
                cache.close()
            engine.dispose()

    app = ProtectedFastAPI(title="Doctor Work Platform", version="0.1.0", lifespan=lifespan)
    app.middleware("http")(audit_request)
    app.state.settings = settings
    app.include_router(auth.router)
    app.include_router(signup.router)
    app.include_router(face_login.router)
    app.include_router(grants.router)
    # T30/T31/T32. Uploaded materials live under `uploads/meeting/` and are
    # served by `GET /api/materials/{id}/download` rather than by StaticFiles:
    # T31 scenario S2 requires a non-participant's downloaded URL to answer 403,
    # and a static mount would hand the bytes over without asking.
    app.include_router(meetings.router)
    app.state.sessions = session_factory(engine)
    app.state.engine = engine
    app.state.cache = cache

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.status_code, "message": str(exc.detail), "data": None},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        fields = [
            ".".join(str(part) for part in error["loc"] if part != "body") for error in exc.errors()
        ]
        message = f"Invalid request: {', '.join(fields)}" if fields else "Invalid request"
        return JSONResponse(
            status_code=422, content={"code": 422, "message": message, "data": None}
        )

    @app.exception_handler(RedisError)
    async def redis_error(request, exc):
        return JSONResponse(
            status_code=503, content={"code": 503, "message": "Redis unavailable", "data": None}
        )

    @app.get("/health", response_model=auth_schemas.HealthResponse)
    @app.get("/api/health", response_model=auth_schemas.HealthResponse)
    def health():
        # The key is "db", not "database": HealthResponse in docs/api/openapi.yaml
        # is the source of truth, and backend/app/auth_schemas.py is generated
        # from it by scripts/generate_auth_schemas.py.
        checks = {"db": "ok", "redis": "disabled"}
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            checks["db"] = "down"
        if app.state.cache is not None:
            try:
                app.state.cache.ping()
                checks["redis"] = "ok"
            except RedisError:
                checks["redis"] = "down"
        return _ok(checks)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        return JSONResponse(
            status_code=503,
            content={"code": 503, "message": "Database unavailable", "data": None},
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        return JSONResponse(
            status_code=500, content={"code": 500, "message": "Internal server error", "data": None}
        )

    @app.get("/api/health/live")
    def live():
        return {**_ok({"status": "ok"}), "status": "ok"}

    @app.get("/api/health/ready")
    def ready():
        # Same key and vocabulary as /health, so one consumer can read both.
        checks = {"db": "ok", "redis": "disabled"}
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                connection.execute(select(Department.id).limit(1))
        except SQLAlchemyError:
            checks["db"] = "down"
        if app.state.cache is not None:
            try:
                app.state.cache.ping()
                checks["redis"] = "ok"
            except RedisError:
                checks["redis"] = "down"
        available = "down" not in checks.values()
        return JSONResponse(
            status_code=200 if available else 503,
            content={
                "code": 0 if available else 503,
                "message": "ok" if available else "Dependencies unavailable",
                "data": checks,
                "status": "ok" if available else "down",
                "checks": checks,
            },
        )

    @app.get(
        "/api/departments",
        response_model=DepartmentListResponse,
        summary="科室列表 / List departments",
        description="下拉框和筛选使用的科室主数据。/ Department master data.",
    )
    def departments(db: DB):
        return _ok(
            [
                DepartmentRead.model_validate(department)
                for department in db.scalars(select(Department).order_by(Department.id))
            ]
        )

    @app.get(
        "/api/patients",
        response_model=PatientListResponse,
        summary="搜索患者 / Search patients",
        description=(
            "姓名模糊、患者编号精确、症状标签、入院日期区间四个条件可以任意 AND 组合；"
            "症状标签可重复传参，命中任意一个即可；四个条件都留空时返回全量，"
            "默认按 created_at 倒序分页。\n\n"
            "`department` 是第五个条件，按科室名精确匹配，与上面四个条件叠加而不是替换它们；"
            "它只能收窄 T09 的科室范围，不能放宽。传入未登记的科室名得到空列表，"
            "而不是 404：筛选条件不匹配不是错误。\n\n"
            "Fuzzy name, exact patient number, symptom tag and admission-date range "
            "combine with AND; repeat `symptom_tags` to match any of several tags. With "
            "no filter the whole table is returned, ordered by `created_at` descending. "
            "The payload is `{items, total, page, size}`.\n\n"
            "`department` is a fifth condition that matches the department name exactly "
            "and stacks with the other four rather than replacing them. It can only narrow "
            "the T09 scope, never widen it. An unknown department name yields an empty "
            "list rather than a 404: a filter that matches nothing is not an error."
        ),
        responses={422: {"model": ErrorResponse}},
    )
    def patients(
        db: DB,
        pagination: Annotated[Pagination, Depends()],
        name: str = Query("", max_length=100, description="姓名模糊匹配 / Fuzzy name match"),
        patient_no: str = Query(
            "", max_length=20, description="患者编号精确匹配 / Exact patient number"
        ),
        symptom_tags: Annotated[
            list[str] | None,
            Query(
                description=(
                    "症状标签精确匹配；可重复传参，命中任意一个即算匹配 / "
                    "Exact symptom tag; repeat the parameter to match any of several tags"
                )
            ),
        ] = None,
        department: str = Query(
            "", max_length=100, description="科室名称精确匹配 / Exact department name"
        ),
        admitted_from: Annotated[
            date | None,
            Query(description="入院日期起（含）/ Admission date from, inclusive"),
        ] = None,
        admitted_to: Annotated[
            date | None,
            Query(description="入院日期止（含）/ Admission date to, inclusive"),
        ] = None,
    ):
        page, size = pagination.page, pagination.size
        if admitted_from and admitted_to and admitted_from > admitted_to:
            raise HTTPException(422, "admitted_from must not be later than admitted_to")
        conditions = [Patient.deleted_at.is_(None), patient_scope(db.info["user"])]
        if name:
            conditions.append(Patient.name.contains(name, autoescape=True))
        if patient_no:
            conditions.append(Patient.patient_no == patient_no)
        if symptom_tags:
            conditions.append(
                or_(
                    *[
                        Patient.symptom_tags.contains(f",{tag},", autoescape=True)
                        for tag in symptom_tags
                    ]
                )
            )
        if department:
            # Stacks on top of `grants.patient_scope` rather than replacing it, so a
            # non-admin naming someone else's department narrows their own scope to
            # nothing instead of widening it. `patient_scope` is already in
            # `conditions`, and AND-ing cannot loosen it.
            conditions.append(Patient.department.has(Department.name == department))
        if admitted_from:
            conditions.append(Patient.admitted_at >= admitted_from)
        if admitted_to:
            conditions.append(Patient.admitted_at <= admitted_to)
        total = db.scalar(select(func.count()).select_from(Patient).where(*conditions)) or 0
        rows = list(
            db.scalars(
                select(Patient)
                .where(*conditions)
                .order_by(Patient.created_at.desc(), Patient.id.desc())
                .offset((page - 1) * size)
                .limit(size)
            )
        )
        stats = _allergy_stats(db, [row.id for row in rows])
        return _ok(
            PatientListData(
                items=[_summary(row, *stats.get(row.id, (0, False))) for row in rows],
                total=total,
                page=page,
                size=size,
            )
        )

    @app.post(
        "/api/patients",
        response_model=PatientResponse,
        summary="新建患者 / Create a patient",
        description=(
            "patient_no 由系统生成并返回，客户端不可提交。缺少必填字段时返回 422，"
            "message 中直接给出字段名。\n\n"
            "The server generates and returns the unique `patient_no`; the client does "
            "not supply one. A missing required field is a 422 whose `message` names it."
        ),
        responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
    )
    def create_patient(body: PatientCreate, db: DB):
        department_id = _department_id(db, body.department)
        for _ in range(PATIENT_NO_RETRIES):
            patient = Patient(
                patient_no=_next_patient_no(db),
                name=body.name,
                gender=body.gender,
                birth_date=body.birth_date,
                department_id=department_id,
                notes=body.notes,
                phone_enc=crypto.encrypt(body.phone) if body.phone else None,
                id_card_enc=crypto.encrypt(body.id_card) if body.id_card else None,
                symptom_tags=join_tags(body.symptom_tags),
                admitted_at=body.admitted_at,
            )
            db.add(patient)
            try:
                db.flush()
            except IntegrityError:
                # A concurrent request claimed the number first; take the next one.
                db.rollback()
                continue
            _audit(db, "patient.create", patient.id)
            db.commit()
            # Echo stored values: MySQL DATETIME keeps whole seconds, so the
            # in-memory microseconds would not match a later read.
            db.refresh(patient)
            return _ok(_detail(patient, [], 0, False))
        raise HTTPException(409, "Could not allocate a patient number, please retry")

    @app.get(
        "/api/patients/{patient_no}",
        response_model=PatientResponse,
        summary="患者详情 / Read a patient",
        description=(
            "返回单条患者记录及其过敏列表；手机号和身份证为脱敏值。过敏列表与 T21 "
            "校验引擎读取的是同一个函数，避免两处数据漂移。\n\n"
            "One patient plus the allergy list; phone and national ID are masked. The "
            "allergy list comes from the same shared function T21 reads."
        ),
        responses={404: {"model": ErrorResponse}},
    )
    def get_patient(patient_no: str, db: DB):
        mark_audit(db.info["request"], "patient.view", "patient", patient_no)
        patient = _live_patient(db, patient_no)
        allergies = get_patient_allergens(db, patient_no)
        return _ok(_detail(patient, allergies, *_severity_summary(allergies)))

    @app.patch(
        "/api/patients/{patient_no}",
        response_model=PatientResponse,
        summary="更新患者 / Update a patient",
        description=(
            "部分更新：请求体里出现的字段才会被修改。patient_no 由系统生成，不可修改；"
            "phone 或 id_card 传 null 即清空。\n\n"
            "Partial update: only the fields present in the body change. `patient_no` is "
            "server-generated and read-only. Sending null for `phone` or `id_card` clears it."
        ),
        responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
    )
    def update_patient(patient_no: str, body: PatientUpdate, db: DB):
        patient = _live_patient(db, patient_no)
        for field in ("name", "gender", "department"):
            if field in body.model_fields_set and getattr(body, field) is None:
                raise HTTPException(422, f"{field} must not be null")
        updates = body.model_dump(exclude_unset=True)
        if "department" in updates:
            updates["department_id"] = _department_id(db, updates.pop("department"))
        if "phone" in updates:
            phone = updates.pop("phone")
            patient.phone_enc = crypto.encrypt(phone) if phone else None
        if "id_card" in updates:
            id_card = updates.pop("id_card")
            patient.id_card_enc = crypto.encrypt(id_card) if id_card else None
        if "symptom_tags" in updates:
            patient.symptom_tags = join_tags(updates.pop("symptom_tags") or [])
        for field, value in updates.items():
            setattr(patient, field, value)
        _audit(db, "patient.update", patient.id)
        db.commit()
        db.refresh(patient)
        allergies = get_patient_allergens(db, patient_no)
        return _ok(_detail(patient, allergies, *_severity_summary(allergies)))

    @app.delete(
        "/api/patients/{patient_no}",
        response_model=OkResponse,
        summary="删除患者 / Delete a patient",
        description=(
            "软删除：写入 deleted_at，之后列表与详情都不再返回该患者，再次读取返回 404；"
            "过敏记录与审计日志保留原样，不做级联删除。\n\n"
            "Soft delete: `deleted_at` is stamped, the patient disappears from list and "
            "detail reads and a later read returns 404. Allergy rows and the audit trail "
            "stay in place; nothing is cascaded away."
        ),
        responses={404: {"model": ErrorResponse}},
    )
    def delete_patient(patient_no: str, db: DB):
        patient = _live_patient(db, patient_no)
        _audit(db, "patient.delete", patient.id)
        patient.deleted_at = datetime.now(UTC)
        db.commit()
        return _ok(OkData())

    @app.get(
        "/api/allergens",
        response_model=AllergenDictionaryResponse,
        summary="过敏原字典 / List the allergen dictionary",
        description=(
            "覆盖青霉素类、磺胺类、头孢类、阿司匹林、造影剂；记录过敏时允许提交字典外的"
            "自定义值，自定义值一经记录会自动收录进本字典。\n\n"
            "Covers penicillins, sulfonamides, cephalosporins, aspirin and contrast media; "
            "a custom value accepted while recording an allergy is folded into this list "
            "automatically."
        ),
    )
    def allergens(db: DB):
        return _ok([AllergenRead(**entry) for entry in dictionary(db)])

    @app.get(
        "/api/patients/{patient_no}/allergies",
        response_model=AllergyListResponse,
        summary="患者过敏记录 / List a patient's allergies",
        description=(
            "与患者详情接口、T21 校验引擎共用 get_patient_allergens 这一个数据源。\n\n"
            "The same list the patient detail route and the T21 engine read, through the "
            "shared `get_patient_allergens`."
        ),
        responses={404: {"model": ErrorResponse}},
    )
    def patient_allergies(patient_no: str, db: DB):
        mark_audit(db.info["request"], "patient.allergies.view", "patient", patient_no)
        _live_patient(db, patient_no)
        return _ok(
            [
                AllergyRead.model_validate(item, from_attributes=True)
                for item in get_patient_allergens(db, patient_no)
            ]
        )

    @app.post(
        "/api/patients/{patient_no}/allergies",
        response_model=AllergyResponse,
        summary="新增过敏记录 / Record an allergy",
        description=(
            "写入 allergy.create 审计。过敏原取字典编码（如 PENICILLIN），也接受自定义补充，"
            "自定义值会被自动收录进过敏原字典。\n\n"
            "Writes an `allergy.create` audit entry. `allergen` is a dictionary code such "
            "as PENICILLIN; a custom value is accepted and joins the dictionary."
        ),
        responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
    )
    def create_allergy(patient_no: str, body: AllergyCreate, db: DB):
        patient = _live_patient(db, patient_no)
        allergy = Allergy(
            patient_id=patient.id,
            allergen=body.allergen,
            allergy_type=body.allergy_type,
            severity=body.severity,
            reaction=body.reaction,
            recorded_at=body.recorded_at,
        )
        db.add(allergy)
        db.flush()
        _audit(
            db,
            "allergy.create",
            patient.id,
            {
                "id": allergy.id,
                "allergen": allergy.allergen,
                "allergen_name": allergen_name(allergy.allergen),
                "severity": allergy.severity,
            },
        )
        db.commit()
        db.refresh(allergy)
        return _ok(AllergyRead.model_validate(allergy, from_attributes=True))

    def _allergy_with_patient(db: Session, allergy_id: int) -> tuple[Allergy, Patient]:
        allergy = db.get(Allergy, allergy_id)
        patient = db.get(Patient, allergy.patient_id) if allergy else None
        if allergy is None or patient is None or patient.deleted_at is not None:
            raise HTTPException(404, "Allergy not found")
        _live_patient(db, patient.patient_no)
        return allergy, patient

    @app.patch(
        "/api/allergies/{allergy_id}",
        response_model=AllergyResponse,
        summary="修改过敏记录 / Update an allergy",
        description=(
            "部分更新，写入 allergy.update 审计。\n\n"
            "Partial update; writes an `allergy.update` audit entry."
        ),
        responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
    )
    def update_allergy(allergy_id: int, body: AllergyUpdate, db: DB):
        allergy, patient = _allergy_with_patient(db, allergy_id)
        for field in ("allergen", "allergy_type", "severity", "recorded_at"):
            if field in body.model_fields_set and getattr(body, field) is None:
                raise HTTPException(422, f"{field} must not be null")
        for field, value in body.model_dump(exclude_unset=True).items():
            setattr(allergy, field, value)
        _audit(
            db,
            "allergy.update",
            patient.id,
            {
                "id": allergy.id,
                "allergen": allergy.allergen,
                "allergen_name": allergen_name(allergy.allergen),
                "severity": allergy.severity,
            },
        )
        db.commit()
        db.refresh(allergy)
        return _ok(AllergyRead.model_validate(allergy, from_attributes=True))

    @app.delete(
        "/api/allergies/{allergy_id}",
        response_model=OkResponse,
        summary="删除过敏记录 / Delete an allergy",
        description=(
            "写入 allergy.delete 审计，detail 中带被删过敏原的编码与名称，便于追溯。\n\n"
            "Writes an `allergy.delete` audit entry whose `detail` carries the removed "
            "allergen's code and name."
        ),
        responses={404: {"model": ErrorResponse}},
    )
    def delete_allergy(allergy_id: int, db: DB):
        allergy, patient = _allergy_with_patient(db, allergy_id)
        _audit(
            db,
            "allergy.delete",
            patient.id,
            {
                "id": allergy.id,
                "allergen": allergy.allergen,
                "allergen_name": allergen_name(allergy.allergen),
                "severity": allergy.severity,
            },
        )
        db.delete(allergy)
        db.commit()
        return _ok(OkData())

    @app.get(
        "/api/audit-logs",
        response_model=AuditLogListResponse,
        summary="查询审计日志 / Search the audit log",
        description=(
            "T12。**仅管理员**：senior 也会被拒绝，返回 403 且响应体里没有任何日志数据。\n\n"
            "用户 / 时间范围 / 操作类型（另有 `object_type`）四个条件可以任意 AND 组合，"
            "默认按 `created_at` 倒序分页。**列表每行都带 `detail`**，展开行即可看到原文，"
            "不需要逐行再拉一次。\n\n"
            "Administrator only -- a senior physician is refused too, with 403 and no log "
            "data in the body. `user_id`, `action`, `object_type` and the `from`/`to` range "
            "combine with AND, newest first. Every row carries `detail` inline, because the "
            "sign-off criteria require a list row to expand in place."
        ),
        responses={403: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
        dependencies=[Depends(require_permission("audit.read"))],
    )
    def audit_logs(
        db: DB,
        pagination: Annotated[Pagination, Depends()],
        filters: Annotated[AuditFilters, Depends()],
    ):
        page, size = pagination.page, pagination.size
        conditions = filters.conditions()
        total = db.scalar(select(func.count()).select_from(AuditLog).where(*conditions)) or 0
        rows = list(
            db.scalars(
                select(AuditLog)
                .where(*conditions)
                # `id` breaks the tie on purpose: entries written in the same second
                # are ordinary during a demo, and without it the sort is free to put
                # the same row on both page 1 and page 2.
                .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .offset(pagination.offset)
                .limit(size)
            )
        )
        return _ok(
            AuditLogListData(
                items=[AuditLogRead.model_validate(row) for row in rows],
                total=total,
                page=page,
                size=size,
            )
        )

    @app.get(
        "/api/audit-logs/export",
        summary="导出审计日志 CSV / Export the audit log as CSV",
        description=(
            "T12。**仅管理员**。返回 `text/csv` 本身，**不是 JSON 信封**。\n\n"
            "接受的筛选条件与查询接口完全一致，只是不分页；导出必须沿用调用方的当前筛选"
            "而不是导出全表，文件名含时间范围，正文以 UTF-8 BOM 开头，Excel 打开才不乱码。\n\n"
            "Administrator only. Returns `text/csv`, not the JSON envelope. Same filters as "
            "the search endpoint, without pagination. The export honours the caller's current "
            "filters rather than dumping the whole table, the filename carries the time range, "
            "and the body starts with a UTF-8 BOM so Excel opens it without mojibake.\n\n"
            "Registered before any `/{id}` route would be: `export` does not parse as an "
            "integer, so a path parameter declared ahead of this one turns every download "
            "into an unexplained 422."
        ),
        responses={403: {"model": ErrorResponse}},
        dependencies=[Depends(require_permission("audit.export"))],
    )
    def export_audit_logs(
        request: Request,
        db: DB,
        filters: Annotated[AuditFilters, Depends()],
    ):
        conditions = filters.conditions()
        rows = list(
            db.scalars(
                select(AuditLog)
                .where(*conditions)
                .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            )
        )
        # T11 criterion 2 names the audit-log export as a sensitive read that has to be
        # marked by hand: the middleware only records POST/PUT/PATCH/DELETE, so a GET
        # that is not marked leaves no trace at all -- and this is the one endpoint that
        # hands the whole trail to a file.
        mark_audit(
            request,
            "audit.export",
            "audit_log",
            detail={
                "filters": {
                    "user_id": filters.user_id,
                    "action": filters.action or None,
                    "object_type": filters.object_type or None,
                    # isoformat, not the datetime: `detail` is a JSON column and a
                    # datetime in there raises at insert time, which `persist_audit`
                    # swallows -- so the entry would go missing rather than fail loudly.
                    "from": filters.from_.isoformat() if filters.from_ else None,
                    "to": filters.to.isoformat() if filters.to else None,
                },
                "rows": len(rows),
            },
        )
        return Response(
            content=audit_csv(rows),
            # Starlette appends `; charset=utf-8` to a `text/*` media type, and encodes
            # the body with it, which is what keeps the BOM and the Chinese names intact.
            media_type="text/csv",
            headers={
                "Content-Disposition": content_disposition(
                    filename_range(rows, filters.from_, filters.to)
                )
            },
        )

    return app


app = create_app()
