from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, UUIDPrimaryKeyMixin, utcnow


class CheckRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "check_runs"
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    trigger: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    total_jobs: Mapped[int] = mapped_column(Integer, default=0)
    done_jobs: Mapped[int] = mapped_column(Integer, default=0)
    failed_jobs: Mapped[int] = mapped_column(Integer, default=0)
    credits_used: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CheckResult(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "check_results"
    run_id: Mapped[str] = mapped_column(ForeignKey("check_runs.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    competitor_id: Mapped[str | None] = mapped_column(
        ForeignKey("competitors.id"), nullable=True, index=True
    )
    platform: Mapped[str] = mapped_column(String(32), index=True)
    pincode: Mapped[str] = mapped_column(String(12), index=True)
    in_stock: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    mrp: Mapped[float | None] = mapped_column(Float, nullable=True)
    eta_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    screenshot_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class ChangeEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "change_events"
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    competitor_id: Mapped[str | None] = mapped_column(
        ForeignKey("competitors.id"), nullable=True
    )
    platform: Mapped[str] = mapped_column(String(32))
    pincode: Mapped[str] = mapped_column(String(12))
    kind: Mapped[str] = mapped_column(String(32))
    old_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    new_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class CreditLedger(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "credit_ledger"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("check_runs.id"), nullable=True, index=True
    )
    credits: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
