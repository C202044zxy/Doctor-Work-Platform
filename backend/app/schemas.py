from datetime import UTC, date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

TAG_MAX_LENGTH = 50
GENDERS = ("male", "female", "unknown")
ALLERGY_TYPES = ("drug", "food", "other")
ALLERGY_SEVERITIES = ("mild", "moderate", "severe")


def clean_tags(tags: list[str] | None) -> list[str] | None:
    """Trim, reject empty/oversized/comma-bearing tags, and drop duplicates."""
    if tags is None:
        return None
    cleaned: list[str] = []
    for tag in tags:
        value = tag.strip()
        if not value:
            raise ValueError("症状标签不能为空 / Symptom tags must not be blank")
        if "," in value:
            raise ValueError("症状标签不能包含逗号 / Symptom tags must not contain commas")
        if len(value) > TAG_MAX_LENGTH:
            raise ValueError("症状标签过长 / Symptom tag is too long")
        if value not in cleaned:
            cleaned.append(value)
    return cleaned


class AllergyRead(BaseModel):
    id: int = Field(description="主键 / Primary key", examples=[1])
    allergen: str = Field(
        description="过敏原字典编码，如 PENICILLIN / Allergen dictionary code",
        examples=["PENICILLIN"],
    )
    allergy_type: str = Field(
        description="过敏类型：drug / food / other / Allergy category",
        examples=["drug"],
    )
    severity: str = Field(
        description="严重程度：mild / moderate / severe / Severity",
        examples=["severe"],
    )
    reaction: str | None = Field(
        default=None, description="反应描述 / Recorded reaction", examples=["Anaphylaxis"]
    )
    recorded_at: date = Field(
        description="记录日期 / Date the allergy was recorded", examples=["2026-08-01"]
    )


class AllergyCreate(BaseModel):
    allergen: str = Field(
        min_length=1,
        max_length=50,
        description=(
            "过敏原字典编码，支持自定义补充 / Allergen dictionary code, custom values allowed"
        ),
        examples=["PENICILLIN"],
    )
    allergy_type: str = Field(
        description="过敏类型：drug / food / other / Allergy category", examples=["drug"]
    )
    severity: str = Field(
        description="严重程度：mild / moderate / severe / Severity", examples=["severe"]
    )
    recorded_at: date = Field(
        description="记录日期 / Date the allergy was recorded", examples=["2026-08-01"]
    )
    reaction: str | None = Field(
        default=None,
        max_length=255,
        description="反应描述 / Recorded reaction",
        examples=["Anaphylaxis"],
    )
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    @field_validator("allergen")
    @classmethod
    def _normalise_allergen(cls, value: str) -> str:
        """Uppercase the code: the T21 block compares codes, so case must not drift."""
        code = value.upper()
        if not code:
            raise ValueError("过敏原不能为空 / Allergen must not be blank")
        return code

    @field_validator("allergy_type")
    @classmethod
    def _validate_type(cls, value: str) -> str:
        if value not in ALLERGY_TYPES:
            raise ValueError("过敏类型无效 / Allergy type must be drug, food or other")
        return value

    @field_validator("severity")
    @classmethod
    def _validate_severity(cls, value: str) -> str:
        if value not in ALLERGY_SEVERITIES:
            raise ValueError("严重程度无效 / Severity must be mild, moderate or severe")
        return value


class AllergyUpdate(AllergyCreate):
    """Same body as a create: every allergy field is optional on an edit."""

    allergen: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
        description="过敏原字典编码 / Allergen dictionary code",
        examples=["PENICILLIN"],
    )
    allergy_type: str | None = Field(
        default=None, description="过敏类型 / Allergy category", examples=["drug"]
    )
    severity: str | None = Field(
        default=None, description="严重程度 / Severity", examples=["severe"]
    )
    recorded_at: date | None = Field(
        default=None, description="记录日期 / Date recorded", examples=["2026-08-01"]
    )

    @field_validator("allergen")
    @classmethod
    def _normalise_allergen(cls, value: str | None) -> str | None:
        """Uppercase the code, matching the create path; None keeps the stored value."""
        if value is None:
            return None
        code = value.upper()
        if not code:
            raise ValueError("过敏原不能为空 / Allergen must not be blank")
        return code

    @field_validator("allergy_type")
    @classmethod
    def _validate_type(cls, value: str | None) -> str | None:
        if value is not None and value not in ALLERGY_TYPES:
            raise ValueError("过敏类型无效 / Allergy type must be drug, food or other")
        return value

    @field_validator("severity")
    @classmethod
    def _validate_severity(cls, value: str | None) -> str | None:
        if value is not None and value not in ALLERGY_SEVERITIES:
            raise ValueError("严重程度无效 / Severity must be mild, moderate or severe")
        return value


class AllergenRead(BaseModel):
    code: str = Field(description="字典编码 / Dictionary code", examples=["PENICILLIN"])
    name: str = Field(description="显示名称 / Display name", examples=["Penicillins"])


class PatientCreate(BaseModel):
    name: str = Field(
        min_length=1, max_length=100, description="患者姓名 / Patient name", examples=["赵雷"]
    )
    gender: str = Field(description="性别：male / female / unknown / Gender", examples=["male"])
    department: str = Field(
        min_length=1,
        max_length=100,
        description="所属科室名称 / Department name",
        examples=["Cardiology"],
    )
    birth_date: date | None = Field(
        default=None, description="出生日期 / Date of birth", examples=["1983-05-20"]
    )
    phone: str | None = Field(
        default=None,
        max_length=32,
        description=(
            "手机号；AES 加密存储，接口只返回脱敏值 / "
            "Mobile phone; stored AES-encrypted, returned masked"
        ),
        examples=["13800001234"],
    )
    id_card: str | None = Field(
        default=None,
        max_length=32,
        description=(
            "身份证号；AES 加密存储，接口只返回脱敏值 / "
            "National ID; stored AES-encrypted, returned masked"
        ),
        examples=["110101199003071234"],
    )
    symptom_tags: list[str] = Field(
        default_factory=list,
        description="症状标签，可用于组合搜索 / Symptom tags used by the combined search",
        examples=[["胸痛", "发热"]],
    )
    admitted_at: date | None = Field(
        default=None,
        description="入院日期，T13 日期区间搜索使用 / Admission date used by the T13 range search",
        examples=["2026-08-15"],
    )
    notes: str = Field(
        default="",
        max_length=2000,
        description="备注 / Free-text notes",
        examples=["Synthetic record for the demo"],
    )
    allergies: list[AllergyCreate] = Field(
        default_factory=list,
        description=(
            "同一次请求里建立过敏记录，与患者同一事务 / "
            "Allergies to record in the same transaction as the patient"
        ),
        examples=[
            [
                {
                    "allergen": "PENICILLIN",
                    "allergy_type": "drug",
                    "severity": "severe",
                    "recorded_at": "2026-08-01",
                    "reaction": "Anaphylaxis",
                }
            ]
        ],
    )
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    @field_validator("gender")
    @classmethod
    def _validate_gender(cls, value: str) -> str:
        if value not in GENDERS:
            raise ValueError("性别无效 / Gender must be male, female or unknown")
        return value

    @field_validator("symptom_tags")
    @classmethod
    def _validate_tags(cls, tags: list[str]) -> list[str]:
        return clean_tags(tags) or []


class PatientUpdate(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="患者姓名 / Patient name",
        examples=["赵雷"],
    )
    gender: str | None = Field(default=None, description="性别 / Gender", examples=["female"])
    department: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="所属科室名称 / Department name",
        examples=["Cardiology"],
    )
    birth_date: date | None = Field(
        default=None, description="出生日期 / Date of birth", examples=["1983-05-20"]
    )
    phone: str | None = Field(
        default=None,
        max_length=32,
        description="手机号；传 null 清空 / Mobile phone; null clears it",
        examples=["13800001234"],
    )
    id_card: str | None = Field(
        default=None,
        max_length=32,
        description="身份证号；传 null 清空 / National ID; null clears it",
        examples=["110101199003071234"],
    )
    symptom_tags: list[str] | None = Field(
        default=None,
        description="症状标签，整组替换 / Symptom tags, replaced as a whole",
        examples=[["胸痛"]],
    )
    admitted_at: date | None = Field(
        default=None, description="入院日期 / Admission date", examples=["2026-08-15"]
    )
    notes: str | None = Field(
        default=None,
        max_length=2000,
        description="备注 / Free-text notes",
        examples=["Follow-up consultation scheduled"],
    )
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    @field_validator("gender")
    @classmethod
    def _validate_gender(cls, value: str | None) -> str | None:
        if value is not None and value not in GENDERS:
            raise ValueError("性别无效 / Gender must be male, female or unknown")
        return value

    @field_validator("symptom_tags")
    @classmethod
    def _validate_tags(cls, tags: list[str] | None) -> list[str] | None:
        return clean_tags(tags)


class PatientGroupRead(BaseModel):
    id: int = Field(description="主键 / Primary key", examples=[1])
    name: str = Field(description="分组名称 / Group name", examples=["Chronic follow-up"])
    description: str = Field(
        default="", description="分组说明 / Group description", examples=["Monthly review"]
    )
    member_count: int = Field(
        default=0,
        description="组内在册患者数（不含已删除患者）/ Members, excluding soft-deleted patients",
        examples=[2],
    )


class PatientGroupCreate(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=100,
        description="分组名称，同一科室内唯一 / Group name, unique within a department",
        examples=["Chronic follow-up"],
    )
    description: str = Field(
        default="",
        max_length=255,
        description="分组说明 / Group description",
        examples=["Monthly review"],
    )
    department: str | None = Field(
        default=None,
        max_length=100,
        description=(
            "所属科室名，缺省为调用者本科室；指定其它科室需要 data.all / "
            "Owning department; defaults to the caller's, another one needs data.all"
        ),
        examples=["Cardiology"],
    )
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")


class PatientGroupUpdate(BaseModel):
    """Partial edit: only the fields present in the body change."""

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="分组名称 / Group name",
        examples=["Chronic follow-up"],
    )
    description: str | None = Field(
        default=None,
        max_length=255,
        description="分组说明 / Group description",
        examples=["Monthly review"],
    )
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")


class GroupMembersRequest(BaseModel):
    patient_nos: list[str] = Field(
        min_length=1,
        description="患者编号列表 / Patient numbers",
        examples=[["P20260001", "P20260002"]],
    )


class PatientSummary(BaseModel):
    patient_no: str = Field(
        description="系统生成的患者编号 / Server-generated patient number",
        examples=["P20260001"],
    )
    name: str = Field(description="患者姓名 / Patient name", examples=["赵雷"])
    gender: str = Field(description="性别 / Gender", examples=["male"])
    birth_date: date | None = Field(
        default=None, description="出生日期 / Date of birth", examples=["1983-05-20"]
    )
    phone_masked: str | None = Field(
        default=None,
        description="脱敏手机号 / Masked phone number",
        examples=["138****1234"],
    )
    phone: str | None = Field(
        default=None,
        description=(
            "脱敏手机号（与 phone_masked 同值，保留 T13 字段名）/ "
            "Masked phone, same value as phone_masked, kept for T13"
        ),
        examples=["138****1234"],
    )
    department: str = Field(description="科室名称 / Department name", examples=["Cardiology"])
    symptom_tags: list[str] = Field(
        default_factory=list, description="症状标签 / Symptom tags", examples=[["胸痛"]]
    )
    allergy_count: int = Field(
        default=0, description="过敏记录条数 / Number of allergy records", examples=[2]
    )
    has_severe_allergy: bool = Field(
        default=False,
        description="是否存在严重过敏，列表页据此显示红色警示 / Whether a severe allergy exists",
        examples=[True],
    )
    admitted_at: date | None = Field(
        default=None, description="入院日期 / Admission date", examples=["2026-08-15"]
    )
    notes: str = Field(
        default="", description="备注 / Free-text notes", examples=["Synthetic record"]
    )
    created_at: datetime = Field(
        description="创建时间（UTC）/ Creation timestamp (UTC)",
        examples=["2026-09-11T08:30:00Z"],
    )
    model_config = ConfigDict(from_attributes=True)


class PatientDetail(PatientSummary):
    id_card_masked: str | None = Field(
        default=None,
        description="脱敏身份证号 / Masked national ID",
        examples=["110101********1234"],
    )
    id_card: str | None = Field(
        default=None,
        description=(
            "脱敏身份证号（与 id_card_masked 同值，保留 T13 字段名）/ "
            "Masked national ID, same value as id_card_masked, kept for T13"
        ),
        examples=["110101********1234"],
    )
    allergies: list[AllergyRead] = Field(
        default_factory=list,
        description=(
            "过敏记录，详情页警示条与 T21 校验引擎共用的同一份数据 / "
            "Allergies, the shared list the detail banner and the T21 engine read"
        ),
    )
    histories: list[dict] = Field(
        default_factory=list,
        description="既往史条目，由 T16 填充 / Medical history entries, filled in by T16",
    )
    groups: list[PatientGroupRead] = Field(
        default_factory=list,
        description="患者所在分组 / The groups this patient belongs to",
    )


class SuccessBase(BaseModel):
    code: int = Field(default=0, description="0 表示成功 / 0 means success", examples=[0])
    message: str = Field(
        default="ok",
        description="英文提示，供开发者排查 / Developer-facing English message",
        examples=["ok"],
    )


class PatientListData(BaseModel):
    items: list[PatientSummary] = Field(description="当前页患者 / Patients on this page")
    total: int = Field(description="满足筛选条件的总条数 / Total matching records", examples=[42])
    page: int = Field(description="当前页码，从 1 开始 / Current page, starting at 1", examples=[1])
    size: int = Field(description="每页条数 / Page size", examples=[20])


class PatientListResponse(SuccessBase):
    data: PatientListData


class PatientGroupListResponse(SuccessBase):
    data: list[PatientGroupRead] = Field(description="分组列表 / Patient groups")


class PatientGroupResponse(SuccessBase):
    data: PatientGroupRead


class AuditLogRead(BaseModel):
    """The contract's AuditLog, and nothing else.

    `patient_id` and `status_code` are columns on the table but not properties of
    the contract's schema, so they are deliberately absent: `response_model` drops
    whatever is not declared here, which makes this class the thing that keeps the
    endpoint from drifting past `docs/api/openapi.yaml`.

    Most fields are nullable even though the contract marks several of them
    required. The columns are nullable because the audit writer runs on requests
    that failed before an identity was resolved, and `user_id`/`result` are
    genuinely NULL on those rows -- see `test_default_protection_and_uniform_errors`.
    A stricter model would not return a wrong answer, it would return a 500 on the
    one page whose whole purpose is being readable.
    """

    id: int = Field(description="主键 / Primary key", examples=[1])
    user_id: int | None = Field(default=None, description="操作者主键 / Acting user id")
    action: str = Field(description="语义化动作 / Semantic action key", examples=["patient.view"])
    # Snapshotted at write time rather than joined, so a later rename cannot
    # rewrite what the log says happened.
    username: str | None = Field(default=None, description="操作当时的账号 / Account as recorded")
    object_type: str | None = Field(
        default=None, description="对象类型 / Object type", examples=["patient"]
    )
    object_id: str | None = Field(
        default=None, description="对象标识 / Object identifier", examples=["P20260001"]
    )
    ip: str | None = Field(default=None, description="来源地址 / Source address")
    method: str | None = Field(
        default=None, description="HTTP 方法 / HTTP method", examples=["POST"]
    )
    path: str | None = Field(
        default=None, description="路由模板 / Route template", examples=["/api/patients"]
    )
    result: str | None = Field(default=None, description="成功或失败 / success or failure")
    detail: dict | None = Field(
        default=None,
        description="结构化摘要，绝不存请求体 / Structured summary, never a request body",
    )
    created_at: datetime = Field(description="写入时间 / Time written")

    model_config = ConfigDict(from_attributes=True)

    @field_validator("created_at", mode="before")
    @classmethod
    def _assume_utc(cls, value):
        """Tag a naive datetime as UTC.

        SQLite hands back naive datetimes for a column that is always written in
        UTC (`main.py` has `_as_utc` for the same reason). Without the offset the
        browser reads "10:00" as ten o'clock local and the trail shows the wrong
        hour -- which is exactly what T12's "filter by today" scenario checks.
        """
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class AuditLogListData(BaseModel):
    items: list[AuditLogRead] = Field(description="当前页日志 / Audit entries on this page")
    total: int = Field(description="满足筛选条件的总条数 / Total matching records", examples=[42])
    page: int = Field(description="当前页码，从 1 开始 / Current page, starting at 1", examples=[1])
    size: int = Field(description="每页条数 / Page size", examples=[20])


class AuditLogListResponse(SuccessBase):
    data: AuditLogListData


class PatientResponse(SuccessBase):
    data: PatientDetail


class AllergyResponse(SuccessBase):
    data: AllergyRead


class AllergyListResponse(SuccessBase):
    data: list[AllergyRead] = Field(description="过敏记录 / Allergy records")


class AllergenDictionaryResponse(SuccessBase):
    data: list[AllergenRead] = Field(description="过敏原字典 / Allergen dictionary")


class DepartmentRead(BaseModel):
    id: int = Field(description="主键 / Primary key", examples=[1])
    name: str = Field(description="科室名称 / Department name", examples=["Cardiology"])
    model_config = ConfigDict(from_attributes=True)


class DepartmentListResponse(SuccessBase):
    data: list[DepartmentRead] = Field(description="科室列表 / Departments")


class OkData(BaseModel):
    """Empty object: the contract's OkData for operations that return no payload."""


class OkResponse(SuccessBase):
    data: OkData = Field(default_factory=OkData, description="空对象 / Empty object", examples=[{}])


class ErrorResponse(BaseModel):
    code: int = Field(
        description="非 0 错误码，与 HTTP 状态码一致 / Non-zero code equal to the HTTP status",
        examples=[404],
    )
    message: str = Field(
        description="英文错误信息，指明字段或原因 / English message naming the field or cause",
        examples=["Invalid request: name"],
    )
    data: None = Field(
        default=None, description="错误响应固定为 null / Always null on errors", examples=[None]
    )
