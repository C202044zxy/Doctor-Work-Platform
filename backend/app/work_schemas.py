from datetime import date, datetime
from typing import Literal

from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ConsultationCreate(Input):
    patient_no: str = Field(min_length=1, max_length=20)


class MessageCreate(Input):
    content: str = Field(default="", max_length=10000)
    image_url: str | None = Field(default=None, max_length=255)
    client_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def nonempty(self):
        if not self.content and not self.image_url:
            raise ValueError("content or image_url is required")
        return self


class RuleCreate(Input):
    patient_no: str = Field(min_length=1, max_length=20)
    rtype: Literal["medication", "followup", "checkin"]
    title: str = Field(min_length=1, max_length=200)
    cron_expr: str = Field(min_length=1, max_length=100)
    active: bool = True
    health_plan_id: int | None = Field(default=None, gt=0)

    @field_validator("cron_expr")
    @classmethod
    def valid_cron(cls, value):
        CronTrigger.from_crontab(value, timezone="Asia/Shanghai")
        return value


class RuleUpdate(Input):
    patient_no: str | None = None
    rtype: Literal["medication", "followup", "checkin"] | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    cron_expr: str | None = Field(default=None, min_length=1, max_length=100)
    active: bool | None = None

    @model_validator(mode="after")
    def valid_patch(self):
        if not self.model_fields_set or any(
            getattr(self, k) is None for k in self.model_fields_set
        ):
            raise ValueError("A non-null update is required")
        if self.cron_expr:
            CronTrigger.from_crontab(self.cron_expr, timezone="Asia/Shanghai")
        return self


class PlanEntry(Input):
    kind: Literal["medication", "followup", "diet_exercise"]
    text: str = Field(min_length=1, max_length=2000)
    done: bool = False


class PlanWrite(Input):
    patient_no: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=200)
    goals: str = Field(default="", max_length=10000)
    instructions: str = Field(default="", max_length=10000)
    entries: list[PlanEntry] = Field(default_factory=list, max_length=100)
    start_date: date
    end_date: date
    status: Literal["active", "completed", "terminated"] = "active"
    reminder_rule_ids: list[int] = Field(default_factory=list, max_length=100)
    new_reminder_rules: list[RuleCreate] = Field(default_factory=list, max_length=20)

    @field_validator("end_date")
    @classmethod
    def dates(cls, value, info):
        if info.data.get("start_date") and value < info.data["start_date"]:
            raise ValueError("end_date must not precede start_date")
        return value


class OrderItem(Input):
    order_type: Literal["drug"]
    drug_code: str = Field(min_length=1, max_length=50)
    dose: str = Field(min_length=1, max_length=100)
    frequency: str = Field(default="", max_length=100)
    route: str = Field(default="", max_length=100)


class OrderCreate(Input):
    record_id: int = Field(gt=0)
    items: list[OrderItem] = Field(min_length=1, max_length=100)
    override_reason: str = Field(default="", max_length=1000)


# Response types are explicit so Swagger exposes the same work-module vocabulary as
# docs/api/openapi.yaml; other members' paths remain in the hand-written contract.
class Envelope[T](BaseModel):
    code: int = 0
    message: str = "ok"
    data: T


class PageData[T](BaseModel):
    items: list[T]
    total: int
    page: int
    size: int


class RoomRead(BaseModel):
    is_participant: bool = False
    id: int
    patient_no: str
    patient_name: str
    doctor_id: int | None
    doctor_name: str | None
    status: Literal["waiting", "active", "ended"]
    last_message: str
    last_message_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime


class MessageRead(BaseModel):
    id: int
    consultation_id: int
    sender_type: Literal["doctor", "patient_assist"]
    sender_name: str
    content: str
    image_url: str | None
    sent_at: datetime
    client_id: str | None


class UploadRead(BaseModel):
    url: str


class PlanRead(BaseModel):
    id: int
    patient_no: str
    title: str
    goals: str
    instructions: str
    entries: list[PlanEntry]
    start_date: date
    end_date: date
    status: Literal["active", "completed", "terminated"]
    reminder_rule_ids: list[int]
    created_at: datetime


class RuleRead(RuleCreate):
    id: int


class LogRead(BaseModel):
    id: int
    rule_id: int
    patient_no: str
    title: str
    due_at: datetime
    fired_at: datetime
    done: bool
    done_at: datetime | None
    read: bool


class LogPage(PageData[LogRead]):
    unread_count: int


class UnreadRead(BaseModel):
    unread_count: int


class ValidationReason(BaseModel):
    kind: Literal["allergy", "dose"]
    message: str
    severity: str | None = None
    allergen: str | None = None
    normal_range: str | None = None
    observed: str | None = None


class ValidationRead(BaseModel):
    status: Literal["passed", "warning", "blocked"]
    reasons: list[ValidationReason]


class OrderRead(BaseModel):
    id: int
    record_id: int
    patient_no: str
    doctor_id: int
    order_type: Literal["drug"]
    content_json: dict
    status: Literal["active", "stopped"]
    validation_status: Literal["passed", "warning", "blocked"]
    validation_detail: list[ValidationReason]
    validation_result: ValidationRead
    override_reason: str
    created_at: datetime
