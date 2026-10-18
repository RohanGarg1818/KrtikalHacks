from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import ClockTime, FiniteFloat, PatchModel

ChannelName = Literal["telegram", "email"]


class UserSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    briefing_time: str
    quiet_hours_start: str | None
    quiet_hours_end: str | None
    default_thresholds: dict
    channels: dict


class UserSettingsUpdate(PatchModel):
    nullable_fields: ClassVar[frozenset[str]] = frozenset(
        {"quiet_hours_start", "quiet_hours_end"}
    )

    briefing_time: ClockTime | None = None
    quiet_hours_start: ClockTime | None = None
    quiet_hours_end: ClockTime | None = None
    default_thresholds: dict[str, FiniteFloat | None] | None = Field(
        default=None, max_length=20
    )
    channels: dict[ChannelName, bool] | None = None


class PlanChangeRequest(BaseModel):
    plan: Literal["free", "pro", "brand"]


class PlanChangeResponse(BaseModel):
    plan: str
    status: str
    test_mode: bool = True
    adjusted_products: int = 0
    paused_products: int = 0
