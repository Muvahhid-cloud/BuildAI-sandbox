import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

BuildingType = Literal["single_family_house"]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    building_type: BuildingType = "single_family_house"
    region_code: str | None = Field(default=None, min_length=2, max_length=16)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    region_code: str | None = Field(default=None, min_length=2, max_length=16)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    building_type: BuildingType
    region_code: str
    currency: str
    rules_profile_id: str
    current_version_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ProjectList(BaseModel):
    items: list[ProjectOut]
