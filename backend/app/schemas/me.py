from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    business_name: str | None = Field(default=None, max_length=200)
    business_type: str | None = Field(default=None, max_length=32)
    language: str | None = Field(default=None, max_length=8)
    timezone: str | None = Field(default=None, max_length=64)
    default_city: str | None = Field(default=None, max_length=100)
