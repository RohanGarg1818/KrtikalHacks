from datetime import datetime

from pydantic import BaseModel


class HeatmapPin(BaseModel):
    pincode: str
    area: str | None
    lat: float | None
    lng: float | None
    status: str
    price: float | None
    rival_price: float | None
    mrp: float | None
    eta: int | None
    checked_at: datetime | None
    platform: str


class HeatmapSummary(BaseModel):
    in_stock: int
    out_of_stock: int
    price_gap: int
    stale: int
    total: int


class HotZone(BaseModel):
    lat: float
    lng: float
    count: int
    pincodes: list[str]


class HeatmapResponse(BaseModel):
    pins: list[HeatmapPin]
    summary: HeatmapSummary
    hot_zones: list[HotZone]
    platform: str | None
    snapshot: str


class SellerPinDetail(BaseModel):
    in_stock: bool | None
    price: float | None
    mrp: float | None
    eta: int | None
    rating: float | None
    status: str
    checked_at: datetime | None
    run_id: str | None
    screenshot_url: str | None


class RivalPinDetail(BaseModel):
    competitor_id: str
    name: str
    in_stock: bool | None
    price: float | None
    mrp: float | None
    eta: int | None
    rating: float | None
    status: str
    checked_at: datetime | None


class PinPlatformDetail(BaseModel):
    platform: str
    status: str
    seller: SellerPinDetail
    rivals: list[RivalPinDetail]


class PinDetailResponse(BaseModel):
    pincode: str
    area: str
    city: str
    lat: float
    lng: float
    platforms: list[PinPlatformDetail]
