from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app import crypto
from app.config import Settings
from app.database import make_engine, session_factory
from app.models import AuditLog, Department, Patient
from app.schemas import (
    DepartmentListResponse,
    DepartmentRead,
    ErrorResponse,
    PatientCreate,
    PatientListResponse,
    PatientRead,
    PatientResponse,
    PatientUpdate,
    join_tags,
    split_tags,
)

PATIENT_NO_RETRIES = 5


def get_session(request: Request):
    with request.app.state.sessions() as session:
        yield session


DB = Annotated[Session, Depends(get_session)]


def _as_utc(value: datetime) -> datetime:
    """SQLite and MySQL drop the offset, so re-attach UTC before serializing."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _to_read(patient: Patient) -> PatientRead:
    """Serialize a patient, decrypting identifiers only long enough to mask them."""
    return PatientRead(
        id=patient.id,
        patient_no=patient.patient_no,
        name=patient.name,
        department_id=patient.department_id,
        notes=patient.notes,
        phone=crypto.mask_phone(crypto.decrypt(patient.phone_enc)) if patient.phone_enc else None,
        id_card=(
            crypto.mask_id_card(crypto.decrypt(patient.id_card_enc))
            if patient.id_card_enc
            else None
        ),
        symptom_tags=split_tags(patient.symptom_tags),
        admitted_at=patient.admitted_at,
        created_at=_as_utc(patient.created_at),
    )


def _next_patient_no(db: Session) -> str:
    """Return the next free P<year><sequence> number, for example P20260001."""
    prefix = f"P{datetime.now(UTC).year}"
    latest = db.scalar(
        select(func.max(Patient.patient_no)).where(Patient.patient_no.like(f"{prefix}%"))
    )
    tail = latest.removeprefix(prefix) if latest else ""
    sequence = int(tail) + 1 if tail.isdigit() else 1
    return f"{prefix}{sequence:04d}"


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
        yield
        if cache:
            cache.close()
        engine.dispose()

    app = FastAPI(title="Doctor Work Platform", version="0.1.0", lifespan=lifespan)
    app.state.sessions = session_factory(engine)
    app.state.engine = engine
    app.state.cache = cache

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(status_code=exc.status_code, content={"error": {"message": exc.detail}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        fields = [
            ".".join(str(part) for part in error["loc"] if part != "body") for error in exc.errors()
        ]
        message = f"Invalid request: {', '.join(fields)}" if fields else "Invalid request"
        return JSONResponse(
            status_code=422,
            content={"error": {"message": message, "fields": fields}},
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        return JSONResponse(status_code=503, content={"error": {"message": "Database unavailable"}})

    @app.get("/api/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/api/health/ready")
    def ready():
        checks = {"database": "ok", "redis": "disabled"}
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                connection.execute(select(Department.id).limit(1))
        except SQLAlchemyError:
            checks["database"] = "unavailable"
        if app.state.cache is not None:
            try:
                app.state.cache.ping()
                checks["redis"] = "ok"
            except RedisError:
                checks["redis"] = "unavailable"
        available = "unavailable" not in checks.values()
        return JSONResponse(
            status_code=200 if available else 503,
            content={"status": "ok" if available else "unavailable", "checks": checks},
        )

    @app.get(
        "/api/departments",
        response_model=DepartmentListResponse,
        summary="科室列表 / List departments",
        description="下拉框和筛选使用的科室主数据。/ Department master data.",
    )
    def departments(db: DB):
        return {
            "data": [
                DepartmentRead.model_validate(d)
                for d in db.scalars(select(Department).order_by(Department.id))
            ]
        }

    @app.get(
        "/api/patients",
        response_model=PatientListResponse,
        summary="搜索患者 / Search patients",
        description=(
            "姓名模糊、患者编号精确、症状标签精确、入院日期区间四个条件可以任意 AND 组合；"
            "四个条件都留空时返回全量，默认按 created_at 倒序分页。\n\n"
            "Fuzzy name, exact patient number, exact symptom tag and admission-date range "
            "combine with AND. With no filter the whole table is returned, ordered by "
            "created_at descending. The payload is {data, total}."
        ),
        responses={422: {"model": ErrorResponse}},
    )
    def patients(
        db: DB,
        q: str = Query("", max_length=100, description="姓名模糊匹配 / Fuzzy name match"),
        patient_no: str = Query(
            "", max_length=20, description="患者编号精确匹配 / Exact patient number"
        ),
        symptom_tag: str = Query(
            "", max_length=50, description="症状标签精确匹配 / Exact symptom tag"
        ),
        admitted_from: Annotated[
            date | None,
            Query(description="入院日期起（含）/ Admission date from, inclusive"),
        ] = None,
        admitted_to: Annotated[
            date | None,
            Query(description="入院日期止（含）/ Admission date to, inclusive"),
        ] = None,
        offset: int = Query(0, ge=0, description="跳过多少条 / Rows to skip"),
        limit: int = Query(20, ge=1, le=100, description="每页条数 / Page size"),
    ):
        if admitted_from and admitted_to and admitted_from > admitted_to:
            raise HTTPException(422, "admitted_from must not be later than admitted_to")
        conditions = []
        if q:
            conditions.append(Patient.name.contains(q, autoescape=True))
        if patient_no:
            conditions.append(Patient.patient_no == patient_no)
        if symptom_tag:
            conditions.append(Patient.symptom_tags.contains(f",{symptom_tag},", autoescape=True))
        if admitted_from:
            conditions.append(Patient.admitted_at >= admitted_from)
        if admitted_to:
            conditions.append(Patient.admitted_at <= admitted_to)
        rows = db.scalars(
            select(Patient)
            .where(*conditions)
            .order_by(Patient.created_at.desc(), Patient.id.desc())
            .offset(offset)
            .limit(limit)
        )
        total = db.scalar(select(func.count()).select_from(Patient).where(*conditions))
        return {"data": [_to_read(patient) for patient in rows], "total": total}

    @app.post(
        "/api/patients",
        status_code=201,
        response_model=PatientResponse,
        summary="新建患者 / Create a patient",
        description=(
            "患者编号由系统生成，格式 P<年份><四位序号>，如 P20260001；"
            "手机号和身份证以 AES-256-GCM 加密存储，响应只返回脱敏值；"
            "必填字段缺失或为空返回 422，并在 message 中点名该字段。\n\n"
            "The patient number is generated as P<year><sequence>. Phone and national ID "
            "are stored as AES-256-GCM ciphertext and returned masked. A missing or blank "
            "required field returns 422 and names the field."
        ),
        responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
    )
    def create_patient(body: PatientCreate, db: DB):
        if db.get(Department, body.department_id) is None:
            raise HTTPException(404, "Department not found")
        for _ in range(PATIENT_NO_RETRIES):
            patient = Patient(
                patient_no=_next_patient_no(db),
                name=body.name,
                department_id=body.department_id,
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
            db.add(AuditLog(action="patient.create", patient_id=patient.id))
            db.commit()
            return {"data": _to_read(patient)}
        raise HTTPException(409, "Could not allocate a patient number, please retry")

    @app.get(
        "/api/patients/{patient_id}",
        response_model=PatientResponse,
        summary="患者详情 / Read a patient",
        description=(
            "返回单条患者记录；手机号和身份证为脱敏值。"
            "/ One patient; phone and national ID are masked."
        ),
        responses={404: {"model": ErrorResponse}},
    )
    def get_patient(patient_id: int, db: DB):
        patient = db.get(Patient, patient_id)
        if patient is None:
            raise HTTPException(404, "Patient not found")
        return {"data": _to_read(patient)}

    @app.patch(
        "/api/patients/{patient_id}",
        response_model=PatientResponse,
        summary="更新患者 / Update a patient",
        description=(
            "部分更新：请求体里出现的字段才会被修改。patient_no 由系统生成，不可修改；"
            "phone 或 id_card 传 null 即清空。\n\n"
            "Partial update: only the fields present in the body change. patient_no is "
            "server-generated and read-only. Sending null for phone or id_card clears it."
        ),
        responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
    )
    def update_patient(patient_id: int, body: PatientUpdate, db: DB):
        patient = db.get(Patient, patient_id)
        if patient is None:
            raise HTTPException(404, "Patient not found")
        for field in ("name", "department_id", "notes"):
            if field in body.model_fields_set and getattr(body, field) is None:
                raise HTTPException(422, f"{field} must not be null")
        updates = body.model_dump(exclude_unset=True)
        if "department_id" in updates and db.get(Department, updates["department_id"]) is None:
            raise HTTPException(404, "Department not found")
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
        db.add(AuditLog(action="patient.update", patient_id=patient.id))
        db.commit()
        return {"data": _to_read(patient)}

    @app.delete(
        "/api/patients/{patient_id}",
        status_code=204,
        summary="删除患者 / Delete a patient",
        description=(
            "硬删除，不是软删：过敏记录通过外键 ON DELETE CASCADE 一并删除，"
            "审计日志保留 patient_id 作为历史引用，之后的查询返回 404。\n\n"
            "Hard delete, not a soft delete. Allergy rows cascade away through the foreign "
            "key, audit entries keep the numeric patient id as a historical reference, and a "
            "later read returns 404."
        ),
        responses={404: {"model": ErrorResponse}},
    )
    def delete_patient(patient_id: int, db: DB):
        patient = db.get(Patient, patient_id)
        if patient is None:
            raise HTTPException(404, "Patient not found")
        db.add(AuditLog(action="patient.delete", patient_id=patient.id))
        db.delete(patient)
        db.commit()

    return app


app = create_app()
