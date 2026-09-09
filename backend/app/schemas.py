from pydantic import BaseModel, ConfigDict, Field


class PatientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    department_id: int = Field(gt=0)
    notes: str = Field(default="", max_length=2000)
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class PatientRead(PatientCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)


class DepartmentRead(BaseModel):
    id: int
    name: str
    model_config = ConfigDict(from_attributes=True)
