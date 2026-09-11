from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

TAG_MAX_LENGTH = 50


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


def join_tags(tags: list[str]) -> str:
    """Store tags as ",tag,tag," so a tag match cannot hit a longer tag by accident."""
    return f",{','.join(tags)}," if tags else ""


def split_tags(stored: str) -> list[str]:
    return [tag for tag in stored.split(",") if tag]


class PatientCreate(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=100,
        description="患者姓名 / Patient name",
        examples=["赵雷"],
    )
    department_id: int = Field(
        gt=0, description="所属科室主键 / Department primary key", examples=[2]
    )
    notes: str = Field(
        default="",
        max_length=2000,
        description="备注 / Free-text notes",
        examples=["Synthetic record for the demo"],
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
        description="入院日期 / Admission date",
        examples=["2026-08-15"],
    )
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

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
    department_id: int | None = Field(
        default=None, gt=0, description="所属科室主键 / Department primary key", examples=[2]
    )
    notes: str | None = Field(
        default=None,
        max_length=2000,
        description="备注 / Free-text notes",
        examples=["Follow-up consultation scheduled"],
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
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    @field_validator("symptom_tags")
    @classmethod
    def _validate_tags(cls, tags: list[str] | None) -> list[str] | None:
        return clean_tags(tags)


class PatientRead(PatientCreate):
    id: int = Field(description="主键 / Primary key", examples=[1])
    patient_no: str = Field(
        description="系统生成的患者编号 / Server-generated patient number",
        examples=["P20260001"],
    )
    phone: str | None = Field(
        default=None,
        max_length=32,
        description="脱敏手机号 / Masked phone number",
        examples=["138****1234"],
    )
    id_card: str | None = Field(
        default=None,
        max_length=32,
        description="脱敏身份证号 / Masked national ID",
        examples=["110101********1234"],
    )
    created_at: datetime = Field(
        description="创建时间（UTC）/ Creation timestamp (UTC)",
        examples=["2026-09-11T08:30:00Z"],
    )
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class PatientListResponse(BaseModel):
    data: list[PatientRead] = Field(description="当前页患者 / Patients on this page")
    total: int = Field(description="符合条件的记录总数 / Total matching records", examples=[1])


class PatientResponse(BaseModel):
    data: PatientRead = Field(description="患者记录 / Patient record")


class DepartmentRead(BaseModel):
    id: int = Field(description="主键 / Primary key", examples=[1])
    name: str = Field(description="科室名称 / Department name", examples=["Cardiology"])
    model_config = ConfigDict(from_attributes=True)


class DepartmentListResponse(BaseModel):
    data: list[DepartmentRead] = Field(description="科室列表 / Departments")


class ErrorDetail(BaseModel):
    message: str = Field(description="错误信息 / Error message", examples=["Patient not found"])
    fields: list[str] | None = Field(
        default=None, description="校验失败或缺失的字段 / Fields that failed validation"
    )


class ErrorResponse(BaseModel):
    error: ErrorDetail = Field(description="错误对象 / Error object")
