"""Schemas for chat conversations and help topics."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class HelpTopic(BaseModel):
    slug: str
    title: str
    body: str


class HelpTopicListResponse(BaseModel):
    items: list[HelpTopic]


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    product_id: str | None = None


class ChatMessageOut(BaseModel):
    role: str
    content: str
    actions: list[dict] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    created_at: datetime


class ConversationSummary(BaseModel):
    id: str
    title: str
    product_id: str | None = None
    created_at: datetime
    message_count: int = 0


class ConversationListResponse(BaseModel):
    items: list[ConversationSummary]


class ConversationDetail(BaseModel):
    id: str
    title: str
    product_id: str | None = None
    created_at: datetime
    messages: list[ChatMessageOut]


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class MessageResponse(BaseModel):
    source: str
    reply: ChatMessageOut
    actions: list[dict] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
