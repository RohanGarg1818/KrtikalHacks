from datetime import datetime

from pydantic import BaseModel


class StatTile(BaseModel):
    key: str
    label: str
    value: int | float


class DashboardAlert(BaseModel):
    id: str
    product_id: str
    product_name: str | None
    kind: str
    message: str
    evidence: dict
    created_at: datetime
    read: bool


class DashboardRecommendation(BaseModel):
    id: str
    product_id: str
    product_name: str | None
    priority: str
    action_text: str
    impact_text: str
    created_at: datetime


class TelegramStatus(BaseModel):
    connected: bool
    total: int


class DashboardResponse(BaseModel):
    tiles: list[StatTile]
    alerts: list[DashboardAlert]
    recommendations: list[DashboardRecommendation]
    telegram: TelegramStatus
