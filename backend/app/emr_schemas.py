"""Semantic validation layered over generated M4 contract models."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app import emr_contract as contract


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmrField(Input, contract.EmrField):
    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    type: Literal["text", "number", "date", "select", "textarea"]
    required: bool = False
    options: list[str] = Field(default_factory=list)


class Fields(Input, contract.FieldsJson):
    fields: list[EmrField] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_fields(self):
        if len({f.key for f in self.fields}) != len(self.fields):
            raise ValueError("Duplicate field keys")
        if any(f.type == "select" and not f.options for f in self.fields):
            raise ValueError("Select fields require options")
        return self


class TemplateWrite(Input, contract.EmrTemplateWriteRequest):
    name: str = Field(min_length=1)
    description: str = ""
    fields_json: Fields
    is_active: bool = True


class RecordCreate(Input, contract.EmrRecordCreateRequest):
    patient_no: str
    template_id: int


class RecordUpdate(Input, contract.EmrRecordUpdateRequest):
    content_json: dict[str, Any]
    version: int = Field(ge=1)
    revision: int = Field(ge=1)


class Amendment(Input, contract.AmendmentRequest):
    content_json: dict[str, Any]


class Review(Input, contract.ReviewRequest):
    action: Literal["approve", "reject"]
    comment: str = ""


class OrderItem(Input, contract.OrderItemInput):
    order_type: Literal["drug", "lab", "exam"]
    drug_code: str = ""
    dose: str = ""
    frequency: str = ""
    route: str = ""


class OrderCreate(Input, contract.OrderCreateRequest):
    record_id: int
    items: list[OrderItem] = Field(min_length=1)
    override_reason: str = ""


class OrderValidate(Input, contract.OrderValidateRequest):
    patient_no: str
    items: list[OrderItem] = Field(min_length=1)
