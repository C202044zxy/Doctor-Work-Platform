"""The meetings slice of `docs/api/openapi.yaml`, hand-written like `app.schemas`.

Its own module so the contract's field names are stated once: the routes build
their payloads from these models, and `response_model` drops anything a route
returns that is not declared here -- which is what keeps the JSON on the wire
equal to the contract instead of drifting one field at a time.
"""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.schemas import SuccessBase


class MeetingStatus(str, Enum):
    """T30 S1. `declined` is a real state, not a deletion; there is no `archived`."""

    requested = "requested"
    accepted = "accepted"
    declined = "declined"
    in_progress = "in_progress"
    completed = "completed"


class MeetingParticipant(BaseModel):
    user_id: int
    name: str
    department: str
    status: Literal["invited", "accepted", "declined"]


class MeetingCreateRequest(BaseModel):
    """患者 + 受邀专家 + 目的, exactly the three inputs T30 §2 lists.

    `purpose` is required and is returned by every read; `scheduled_at` is not
    one of the three, so a client that sends no time must still succeed and the
    backend stores the moment of the request.
    """

    model_config = ConfigDict(extra="forbid")
    patient_no: str = Field(min_length=1, max_length=20, examples=["P20260001"])
    participant_ids: list[int] = Field(min_length=1, description="One temp_grant per id.")
    purpose: str = Field(min_length=1, examples=["Confirm the diuretic dose before discharge."])
    title: str | None = Field(default=None, max_length=200)
    scheduled_at: AwareDatetime | None = None

    @field_validator("purpose", "title")
    @classmethod
    def not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("不能为空 / must not be blank")
        return value.strip()


class Meeting(BaseModel):
    id: int
    title: str
    patient_no: str
    initiator_id: int
    initiator_name: str
    status: MeetingStatus
    scheduled_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    purpose: str
    participants: list[MeetingParticipant]
    created_at: datetime


class MeetingMaterial(BaseModel):
    id: int
    meeting_id: int
    filename: str
    content_type: str
    size_bytes: int
    uploaded_by: int
    uploaded_by_name: str
    uploaded_at: datetime


class ExpertOpinion(BaseModel):
    expert_id: int
    expert_name: str | None = None
    opinion: str = Field(min_length=1)


class MeetingReportWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expert_opinions: list[ExpertOpinion] = Field(min_length=1)
    conclusion: str = Field(min_length=1)
    status: Literal["draft", "final"] = "final"

    @field_validator("conclusion")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("结论不能为空 / conclusion must not be blank")
        return value.strip()


class MeetingReport(BaseModel):
    id: int
    meeting_id: int
    expert_opinions: list[ExpertOpinion]
    conclusion: str
    status: Literal["draft", "final"]
    version: int
    created_by: int
    created_by_name: str
    created_at: datetime


class Doctor(BaseModel):
    """One row of the invite picker's directory. No contact details.

    M1-07 ships `/api/users` for administrators only, and T30 S1 has `dr_wang`,
    a *junior*, initiate the consultation -- so the picker cannot read that
    endpoint. This authenticated, read-only directory is what M5 needs; M1-07
    supersedes it and it can then be deleted.
    """

    id: int
    username: str
    name: str
    title: str
    department: str


class DoctorListData(BaseModel):
    items: list[Doctor]
    total: int
    page: int
    size: int


class MeetingListData(BaseModel):
    items: list[Meeting]
    total: int
    page: int
    size: int


class DoctorListResponse(SuccessBase):
    data: DoctorListData


class MeetingListResponse(SuccessBase):
    data: MeetingListData


class MeetingResponse(SuccessBase):
    data: Meeting


class MeetingParticipantListResponse(SuccessBase):
    data: list[MeetingParticipant]


class MeetingMaterialListResponse(SuccessBase):
    data: list[MeetingMaterial]


class MeetingMaterialResponse(SuccessBase):
    data: MeetingMaterial


class MeetingReportResponse(SuccessBase):
    data: MeetingReport
