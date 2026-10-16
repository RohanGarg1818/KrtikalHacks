from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
