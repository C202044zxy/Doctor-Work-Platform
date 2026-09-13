"""B-owned T20/T25/T26/T35/T36 persistence; no A/D feature tables."""

from datetime import UTC, date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


def now():
    return datetime.now(UTC)


class MedicalOrder(Base):
    __tablename__ = "medical_order"
    id: Mapped[int] = mapped_column(primary_key=True)
    # A owns medical_record and its migration. The integration loader verifies this
    # reference in the same transaction; add its FK when A's table is delivered.
    record_id: Mapped[int] = mapped_column(index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    order_type: Mapped[str] = mapped_column(String(20), default="drug")
    content_json: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="active")
    validation_status: Mapped[str] = mapped_column(String(20))
    validation_detail: Mapped[list] = mapped_column(JSON)
    override_reason: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Consultation(Base):
    __tablename__ = "consultation"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    doctor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="waiting", index=True)
    last_message: Mapped[str] = mapped_column(String(200), default="")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ConsultMessage(Base):
    __tablename__ = "consult_message"
    __table_args__ = (
        UniqueConstraint("consultation_id", "sender_id", "client_id", name="uq_message_retry"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    consultation_id: Mapped[int] = mapped_column(ForeignKey("consultation.id"), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    client_id: Mapped[str | None] = mapped_column(String(64))
    sender_type: Mapped[str] = mapped_column(String(20))
    sender_name: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str | None] = mapped_column(String(255))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class ImageUpload(Base):
    __tablename__ = "image_upload"
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(100), unique=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    consultation_id: Mapped[int | None] = mapped_column(ForeignKey("consultation.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class HealthPlan(Base):
    __tablename__ = "health_plan"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200))
    goals: Mapped[str] = mapped_column(Text, default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    entries: Mapped[list] = mapped_column(JSON, default=list)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReminderRule(Base):
    __tablename__ = "reminder_rule"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    health_plan_id: Mapped[int | None] = mapped_column(ForeignKey("health_plan.id"), index=True)
    rtype: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    cron_expr: Mapped[str] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReminderLog(Base):
    __tablename__ = "reminder_log"
    __table_args__ = (UniqueConstraint("rule_id", "due_at", name="uq_reminder_due"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("reminder_rule.id"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read: Mapped[bool] = mapped_column(Boolean, default=False)
