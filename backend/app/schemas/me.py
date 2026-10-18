from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from .common import Language, PatchModel, TimezoneName, optional_text, required_text


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    email: str
    business_name: str | None
    business_type: str
    language: str
    timezone: str
    default_city: str | None
    created_at: datetime


class UsageResponse(BaseModel):
    products: int
    pincodes: int
    checks_this_week: int


class MeResponse(BaseModel):
    profile: ProfileResponse
    plan: str
    usage: UsageResponse


PersonName = required_text(200)
BusinessName = optional_text(200)
BusinessType = required_text(32)
CityName = optional_text(100)


class ProfileUpdate(PatchModel):
    nullable_fields: ClassVar[frozenset[str]] = frozenset(
        {"business_name", "default_city"}
    )

    name: PersonName | None = None
    business_name: BusinessName = None
    business_type: BusinessType | None = None
    language: Language | None = None
    timezone: TimezoneName | None = None
    default_city: CityName = None
