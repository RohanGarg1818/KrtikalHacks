from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, UUIDPrimaryKeyMixin, utcnow


class TelegramLinkCode(Base):
    __tablename__ = "telegram_link_codes"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    chat_type: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TelegramLink(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "telegram_links"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    chat_id: Mapped[str] = mapped_column(String(100), index=True)
    chat_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    alert_types: Mapped[list] = mapped_column(JSON, default=list)
    briefing_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
