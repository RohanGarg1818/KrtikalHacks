from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    brand: str | None = Field(default=None, max_length=200)
    search_query: str = Field(min_length=1, max_length=500)
    image_url: str | None = Field(default=None, max_length=1000)
    cost_price: float | None = Field(default=None, ge=0)
    min_margin_pct: float = Field(default=10, ge=0, le=1000)
    max_change_pct: float = Field(default=10, ge=0, le=1000)
    floor_price: float | None = Field(default=None, ge=0)
    check_frequency: str = "daily"
    volatile_boost: bool = False
    approval_required: bool = True
    paused: bool = False


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    brand: str | None = Field(default=None, max_length=200)
    search_query: str | None = Field(default=None, min_length=1, max_length=500)
    image_url: str | None = Field(default=None, max_length=1000)
    cost_price: float | None = Field(default=None, ge=0)
    min_margin_pct: float | None = Field(default=None, ge=0, le=1000)
    max_change_pct: float | None = Field(default=None, ge=0, le=1000)
    floor_price: float | None = Field(default=None, ge=0)
    check_frequency: str | None = None
    volatile_boost: bool | None = None
    approval_required: bool | None = None
    paused: bool | None = None


class ProductResponse(ProductCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    created_at: datetime


class ProductCard(ProductResponse):
    status_strip: list[dict[str, str]]
    price_position_vs_avg_rival: float | None
    last_checked: datetime | None
    telegram_connected: bool


class PincodeSelection(BaseModel):
    platforms: list[str] = Field(min_length=1)
    pincodes: list[str] = Field(min_length=1)


class AlertRuleInput(BaseModel):
    kind: str
    threshold: float | None = None
    rule_text: str | None = None
    rule_json: dict = Field(default_factory=dict)
    active: bool = True


class AlertRulesUpdate(BaseModel):
    rules: list[AlertRuleInput]


class CompetitorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    platform: str
    url: str | None = Field(default=None, max_length=1000)
    search_query: str | None = Field(default=None, max_length=500)
    confirmed: bool = False


class CompetitorResponse(CompetitorCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    product_id: str


class CompetitorDiscoveryRequest(BaseModel):
    query: str | None = Field(default=None, min_length=1, max_length=500)


class CompetitorDiscoveryResponse(BaseModel):
    suggestions: list[CompetitorCreate]
    source: str
