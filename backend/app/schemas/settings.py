from pydantic import BaseModel, ConfigDict, Field


class UserSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    briefing_time: str
    quiet_hours_start: str | None
    quiet_hours_end: str | None
    default_thresholds: dict
    channels: dict


class UserSettingsUpdate(BaseModel):
    briefing_time: str | None = Field(
        default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )
    quiet_hours_start: str | None = Field(
        default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )
    quiet_hours_end: str | None = Field(
        default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )
    default_thresholds: dict | None = None
    channels: dict | None = None


class PlanChangeRequest(BaseModel):
    plan: str


class PlanChangeResponse(BaseModel):
    plan: str
    status: str
