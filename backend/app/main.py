from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import make_engine, session_factory
from app.models import AuditLog, Department, Patient
from app.schemas import DepartmentRead, PatientCreate, PatientRead


def get_session(request: Request):
    with request.app.state.sessions() as session:
        yield session


DB = Annotated[Session, Depends(get_session)]


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
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
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "message": "Invalid request",
                    "fields": [str(e["loc"]) for e in exc.errors()],
                }
            },
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

    @app.get("/api/departments")
    def departments(db: DB):
        return {
            "data": [
                DepartmentRead.model_validate(d)
                for d in db.scalars(select(Department).order_by(Department.id))
            ]
        }

    @app.get("/api/patients")
    def patients(
        db: DB,
        q: str = Query("", max_length=100),
        offset: int = Query(0, ge=0),
        limit: int = Query(20, ge=1, le=100),
    ):
        condition = Patient.name.contains(q, autoescape=True)
        rows = db.scalars(
            select(Patient).where(condition).order_by(Patient.id.desc()).offset(offset).limit(limit)
        )
        total = db.scalar(select(func.count()).select_from(Patient).where(condition))
        return {"data": [PatientRead.model_validate(p) for p in rows], "total": total}

    @app.post("/api/patients", status_code=201)
    def create_patient(body: PatientCreate, db: DB):
        if db.get(Department, body.department_id) is None:
            raise HTTPException(404, "Department not found")
        patient = Patient(**body.model_dump())
        db.add(patient)
        db.flush()
        db.add(AuditLog(action="patient.create", patient_id=patient.id))
        db.commit()
        return {"data": PatientRead.model_validate(patient)}

    @app.get("/api/patients/{patient_id}")
    def get_patient(patient_id: int, db: DB):
        patient = db.get(Patient, patient_id)
        if patient is None:
            raise HTTPException(404, "Patient not found")
        return {"data": PatientRead.model_validate(patient)}

    @app.delete("/api/patients/{patient_id}", status_code=204)
    def delete_patient(patient_id: int, db: DB):
        patient = db.get(Patient, patient_id)
        if patient is None:
            raise HTTPException(404, "Patient not found")
        db.add(AuditLog(action="patient.delete", patient_id=patient.id))
        db.delete(patient)
        db.commit()

    return app


app = create_app()
