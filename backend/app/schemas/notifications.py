"""Schemas for alerts, Telegram linking, and notifications."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AlertResponse(BaseModel):
    id: str
    product_id: str
    product_name: str | None = None
    kind: str
    message: str
    evidence: dict = Field(default_factory=dict)
    read: bool
    sent_telegram: bool
    created_at: datetime


class AlertListResponse(BaseModel):
    items: list[AlertResponse]
    unread: int = 0


class MarkReadResponse(BaseModel):
    marked: int


class LinkCodeResponse(BaseModel):
    code: str
    deeplink: str
    expires_at: datetime
    product_id: str


class TelegramChatLink(BaseModel):
    id: str
    chat_id: str
    chat_title: str | None = None
    alert_types: list[str] = Field(default_factory=list)
    briefing_time: str | None = None
    connected_at: datetime


class TelegramStatusResponse(BaseModel):
    enabled: bool
    bot_running: bool
    bot_username: str | None = None
    links: list[TelegramChatLink] = Field(default_factory=list)
