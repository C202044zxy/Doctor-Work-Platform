"""M4 persistent records, immutable submission snapshots and prescription rules."""

from datetime import UTC, datetime
from typing import ClassVar

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base, Patient, User


def now():
    return datetime.now(UTC)


class EmrTemplate(Base):
    __tablename__ = "emr_template"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(default="")
    fields_json: Mapped[dict] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(default=True)


class EmrRecord(Base):
    __tablename__ = "emr_record"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("emr_template.id"))
    template_snapshot: Mapped[dict] = mapped_column(JSON)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    content_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    version: Mapped[int] = mapped_column(default=1)
    revision: Mapped[int] = mapped_column(default=1)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    review_comment: Mapped[str | None]
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    patient: Mapped[Patient] = relationship(lazy="joined")
    author: Mapped[User] = relationship(foreign_keys=[author_id], lazy="joined")
    __mapper_args__: ClassVar[dict] = {"version_id_col": revision}


class EmrVersion(Base):
    __tablename__ = "emr_version"
    __table_args__ = (UniqueConstraint("record_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("emr_record.id"), index=True)
    version: Mapped[int]
    content_json: Mapped[dict] = mapped_column(JSON)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    author: Mapped[User] = relationship(lazy="joined")


class Drug(Base):
    __tablename__ = "drug"
    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str]
    spec: Mapped[str]
    default_frequency: Mapped[str]
    contraindications: Mapped[list] = mapped_column(JSON)
    dose_min: Mapped[str]
    dose_max: Mapped[str]
    dose_rule: Mapped[dict] = mapped_column(JSON)


class MedicalOrder(Base):
    __tablename__ = "medical_order"
    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("emr_record.id"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    order_type: Mapped[str] = mapped_column(String(20))
    content_json: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="active")
    validation_status: Mapped[str] = mapped_column(String(20))
    validation_detail: Mapped[list] = mapped_column(JSON)
    override_reason: Mapped[str] = mapped_column(default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    patient: Mapped[Patient] = relationship(lazy="joined")
