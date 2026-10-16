"""Schemas for alerts, Telegram linking, and notifications."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

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


class LinkCodeRequest(BaseModel):
    chat_type: Literal["personal", "group"] = "personal"


class LinkCodeResponse(BaseModel):
    code: str
    deep_link: str
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
    status: Literal["not_connected", "waiting", "connected"]
    chat_title: str | None = None
    enabled: bool
    bot_running: bool
    bot_username: str | None = None
    links: list[TelegramChatLink] = Field(default_factory=list)


class TelegramLinkUpdate(BaseModel):
    alert_types: list[str] | None = None
    briefing_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")


class TelegramTestResponse(BaseModel):
    sent: bool
    chat_id: str | None = None
    message: str
