"""M6: vitals, health plans, reminder rules and their log, periodic assessments.

Hand-written from `docs/api/openapi.yaml`, like `app.meeting_schemas` and
`app.schemas`. Its own module so the contract's field names are stated once: the
routes build their payloads from these models, and `response_model` drops
anything a route returns that is not declared here -- which is what keeps the
JSON on the wire equal to the contract instead of drifting one field at a time.

Two checks the contract puts on the server deliberately live in the routes rather
than here, because pydantic cannot name the field for them and the contract wants
the 422 to name it: a future `recorded_at` / `assessed_at`, an `end_date` before
its `start_date`, and a `bp` reading with no diastolic value. See the note in
`app.health`.
"""

from datetime import date, datetime
from enum import Enum

from apscheduler.triggers.cron import CronTrigger
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.schemas import SuccessBase


class VitalType(str, Enum):
    """The contract spells these `bp` / `gl` / `hr`, not long names.

    `weight` is deliberately absent: M6's completion criteria say the enum holds
    exactly these three.
    """

    bp = "bp"
    gl = "gl"
    hr = "hr"


class VitalSource(str, Enum):
    """`manual` for staff entry, `mock` for the simulation script.

    Kept distinct so a demonstration reading can be told apart from a real one.
    """

    manual = "manual"
    mock = "mock"


class ReminderType(str, Enum):
    """T36 names the field `rtype`; these are its three values."""

    medication = "medication"
    followup = "followup"
    checkin = "checkin"


class HealthPlanStatus(str, Enum):
    active = "active"
    completed = "completed"
    terminated = "terminated"


class PlanEntryKind(str, Enum):
    medication = "medication"
    followup = "followup"
    diet_exercise = "diet_exercise"


# ---------- Vital signs (T33 / T34) ----------


class VitalSignRead(BaseModel):
    id: int = Field(description="主键 / Primary key", examples=[1])
    patient_no: str = Field(description="患者编号 / Patient business key", examples=["P20260001"])
    sign_type: VitalType
    value: float = Field(
        description="收缩压时为其数值；gl/hr 单独成值 / Systolic for `bp`; stands alone otherwise"
    )
    value_secondary: float | None = Field(default=None, description="舒张压 / Diastolic for `bp`")
    unit: str = Field(examples=["mmHg"])
    recorded_at: datetime = Field(description="测量时间 / When it was taken")
    source: VitalSource
    is_abnormal: bool = Field(
        description="写入时由服务端按阈值判定 / Decided by the server at write time from the threshold"
    )
    recorded_by: int | None = Field(default=None, description="录入者主键 / Recording user id")


class VitalSignCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sign_type: VitalType
    value: float = Field(description="必须是数字，非数字得到 422 / Must parse as a number")
    value_secondary: float | None = Field(
        default=None, description="sign_type 为 bp 时必填 / Required when `sign_type` is `bp`"
    )
    recorded_at: AwareDatetime = Field(description="不得晚于当前时间 / Must not be in the future")
    source: VitalSource = Field(default=VitalSource.manual)


class VitalSignResponse(SuccessBase):
    data: VitalSignRead


class VitalSignListData(BaseModel):
    items: list[VitalSignRead] = Field(description="当前页读数 / Readings on this page")
    total: int = Field(description="满足条件的总条数 / Total matching records")
    page: int = Field(description="当前页码，从 1 开始 / Current page, starting at 1")
    size: int = Field(description="每页条数 / Page size")


class VitalSignListResponse(SuccessBase):
    data: VitalSignListData


class VitalTrendThreshold(BaseModel):
    """The bounds a point was judged against.

    Carries the secondary pair as well: a blood-pressure tooltip has to read
    "160/100 mmHg（超出阈值 140/90）", and with only `min`/`max` it could render
    "140" but not "90".
    """

    min: float
    max: float
    min_secondary: float | None = None
    max_secondary: float | None = None


class VitalTrendPoint(BaseModel):
    recorded_at: datetime
    value: float = Field(description="收缩压 / Systolic for `bp`")
    value_secondary: float | None = Field(
        default=None, description="仅 bp 有点位 / Present for `bp`"
    )
    is_abnormal: bool
    threshold: VitalTrendThreshold


class VitalTrendData(BaseModel):
    """Shaped for ECharts directly: a time series, not raw rows."""

    sign_type: VitalType
    unit: str
    threshold: VitalTrendThreshold
    points: list[VitalTrendPoint] = Field(
        description="区间内无记录时为空数组 / Empty when the range holds no records"
    )


class VitalTrendResponse(SuccessBase):
    data: VitalTrendData


# ---------- Health plans (T35) ----------


class HealthPlanEntry(BaseModel):
    kind: PlanEntryKind
    text: str
    done: bool = False


class HealthPlanWriteEntry(BaseModel):
    """One item as the client writes it. No `done`: the write body has no status."""

    kind: PlanEntryKind
    text: str


class HealthPlanRead(BaseModel):
    id: int
    patient_no: str
    title: str
    goals: str = ""
    instructions: str = ""
    entries: list[HealthPlanEntry] = Field(default_factory=list)
    start_date: date
    end_date: date
    status: HealthPlanStatus
    reminder_rule_ids: list[int] = Field(
        default_factory=list,
        description="与本方案关联的提醒规则 / Reminder rules linked to this plan",
    )
    created_at: datetime


class HealthPlanWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patient_no: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=200)
    goals: str = ""
    instructions: str = ""
    entries: list[HealthPlanWriteEntry] = Field(default_factory=list)
    start_date: date
    end_date: date = Field(description="早于 start_date 得到 422 / Before `start_date` is a 422")
    status: HealthPlanStatus | None = Field(
        default=None, description="创建时缺省为 active / Defaults to `active` on create"
    )
    reminder_rule_ids: list[int] = Field(default_factory=list)
    new_reminder_rules: list["ReminderRuleWriteRequest"] = Field(
        default_factory=list,
        description=(
            "随方案一并创建的规则 / Rules created together with the plan. "
            "新规则还没有 id，所以只靠 reminder_rule_ids 表达不了这个场景。"
        ),
    )


class HealthPlanListData(BaseModel):
    items: list[HealthPlanRead]
    total: int
    page: int
    size: int


class HealthPlanListResponse(SuccessBase):
    data: HealthPlanListData


class HealthPlanResponse(SuccessBase):
    data: HealthPlanRead


# ---------- Reminder rules and their log (T36) ----------


class ReminderRuleRead(BaseModel):
    id: int
    patient_no: str
    rtype: ReminderType
    title: str
    cron_expr: str = Field(examples=["0 9 * * *"])
    active: bool
    health_plan_id: int | None = Field(
        default=None, description="随健康方案创建时写入 / Set when created alongside a plan"
    )


class ReminderRuleWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patient_no: str = Field(min_length=1, max_length=20)
    rtype: ReminderType
    title: str = Field(min_length=1, max_length=200)
    cron_expr: str = Field(max_length=100)
    active: bool = True
    health_plan_id: int | None = None

    @field_validator("cron_expr")
    @classmethod
    def _valid_crontab(cls, value: str) -> str:
        """Reject a malformed expression here rather than in the scheduler.

        A rule whose cron cannot be parsed would otherwise be stored happily and
        then quietly generate nothing forever -- the failure would show up as an
        empty reminder list during the demonstration.
        """
        try:
            CronTrigger.from_crontab(value.strip(), timezone="UTC")
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid cron expression: {value}") from exc
        return value.strip()


class ReminderRuleUpdateRequest(BaseModel):
    """Every field optional, and only the ones present are changed.

    A partial body is the normal case: T36 §4 toggles a rule with
    ``{"active": false}`` alone, which is why this is a separate model from the
    create body rather than a reuse of it.
    """

    model_config = ConfigDict(extra="forbid")
    patient_no: str | None = Field(default=None, min_length=1, max_length=20)
    rtype: ReminderType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    cron_expr: str | None = Field(default=None, max_length=100)
    active: bool | None = None

    @field_validator("cron_expr")
    @classmethod
    def _valid_crontab(cls, value: str | None) -> str | None:
        """Same check as the create body; a patch may not smuggle in a bad cron."""
        if value is None:
            return None
        try:
            CronTrigger.from_crontab(value.strip(), timezone="UTC")
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid cron expression: {value}") from exc
        return value.strip()


class ReminderRuleListResponse(SuccessBase):
    data: list[ReminderRuleRead] = Field(description="提醒规则 / Reminder rules")


class ReminderRuleResponse(SuccessBase):
    data: ReminderRuleRead


class ReminderLogRead(BaseModel):
    id: int
    rule_id: int
    patient_no: str
    title: str
    due_at: datetime = Field(description="计划触发时刻，幂等键的一半 / Half the idempotency key")
    fired_at: datetime
    done: bool
    done_at: datetime | None = None
    read: bool = Field(description="驱动工作台红点 / Drives the workspace red dot")


class ReminderLogData(BaseModel):
    items: list[ReminderLogRead]
    total: int
    page: int
    size: int
    unread: int = Field(
        description="本次请求后的未读数 / Unread after this request, so one response updates the dot"
    )


class ReminderLogListResponse(SuccessBase):
    data: ReminderLogData


class ReminderLogResponse(SuccessBase):
    data: ReminderLogRead


class UnreadCount(BaseModel):
    unread: int = Field(examples=[2])


class UnreadCountResponse(SuccessBase):
    data: UnreadCount


# ---------- Periodic assessments (T37) ----------


class HealthAssessmentRead(BaseModel):
    id: int
    patient_no: str
    period: str = Field(
        description="评估周期，形如 2026-08 / The calendar month assessed", examples=["2026-08"]
    )
    conclusion: str
    plan_adjustment: str = ""
    assessed_by: int
    assessed_by_name: str = Field(default="", description="评估医生姓名 / Assessing physician")
    assessed_at: datetime
    version: int = Field(description="修订次数；修订是新行而不是覆盖 / Revision count")
    updated_at: datetime | None = None


class HealthAssessmentWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period: str = Field(
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description="评估的日历月 YYYY-MM，格式不符得到 422 / The calendar month, as `YYYY-MM`",
        examples=["2026-08"],
    )
    conclusion: str = Field(min_length=1, description="结论必填，空结论得到 422 / Required")
    plan_adjustment: str = ""
    assessed_at: AwareDatetime | None = Field(
        default=None, description="缺省为当前时间；晚于当前时间得到 422 / Defaults to now"
    )


class HealthAssessmentListResponse(SuccessBase):
    data: list[HealthAssessmentRead] = Field(description="评估记录，新的在前 / Newest first")


class HealthAssessmentResponse(SuccessBase):
    data: HealthAssessmentRead


HealthPlanWriteRequest.model_rebuild()
