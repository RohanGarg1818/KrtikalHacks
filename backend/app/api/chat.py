"""Chat endpoints: conversations, messages, and the static help catalog."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_user
from ..models.chat import ChatConversation, ChatMessage
from ..models.checks import CheckResult
from ..models.product import Product
from ..models.user import Subscription, User
from ..schemas.chat import (
    ChatMessageOut,
    ChatRequest,
    ChatResponse,
    ConversationCreate,
    ConversationDetail,
    ConversationListResponse,
    ConversationSummary,
    HelpTopic,
    HelpTopicListResponse,
    MessageCreate,
    MessageResponse,
)
from ..services.ai import get_ai_provider, with_fallback
from ..services.help_topics import get_help_topic, list_help_topics
from ..services.intelligence import build_context
from ..services.plans import daily_credits_used, limits_for
from .products import get_owned_product

router = APIRouter(tags=["chat"])

MAX_MESSAGES_PER_CONVERSATION = 100
HISTORY_WINDOW = 20
# An unfocused chat is grounded in at most this many recently checked products.
UNFOCUSED_PRODUCT_LIMIT = 5
# In-app destinations a chat action may link to; anything else is dropped.
ACTION_PATH = re.compile(
    r"^/(dashboard|products(/[\w-]+(/(settings|telegram|heatmap))?)?|heatmap|help"
    r"|settings|agents)(\?.*)?$"
)

EMPTY_CONTEXT = {
    "product_id": None,
    "product_name": "your products",
    "avg_price": None,
    "cheapest_rival": None,
    "in_stock": None,
    "total_pins": None,
    "rating": None,
    "oos_pins": [],
    "oos_platforms": [],
    "price_gap_pins": 0,
    "stale_pins": 0,
    "hot_zone_count": 0,
    "this_week_avg_price": None,
    "last_week_avg_price": None,
    "recommendation_preview": "",
}


def safe_actions(actions: list[dict]) -> list[dict]:
    return [
        action
        for action in actions
        if isinstance(action.get("path"), str) and ACTION_PATH.match(action["path"])
    ]


async def _unfocused_context(session: AsyncSession, user_id: str, message: str) -> dict:
    """Ground an "all products" chat in the product the message names, else the one
    with the most stock-outs, so answers carry real numbers instead of blanks.

    Only the most recently checked products are considered, so the cost of a
    message does not grow with the size of the catalogue.
    """
    last_checked = (
        select(CheckResult.product_id, func.max(CheckResult.checked_at).label("at"))
        .group_by(CheckResult.product_id)
        .subquery()
    )
    products = list(
        (
            await session.scalars(
                select(Product)
                .outerjoin(last_checked, last_checked.c.product_id == Product.id)
                .where(Product.user_id == user_id)
                .order_by(
                    last_checked.c.at.is_(None),
                    last_checked.c.at.desc(),
                    Product.created_at.desc(),
                )
                .limit(UNFOCUSED_PRODUCT_LIMIT)
            )
        ).all()
    )
    text = message.lower()

    def mention_score(product: Product) -> int:
        words = {w for w in f"{product.name} {product.brand or ''}".lower().split() if len(w) > 3}
        return sum(word in text for word in words)

    named = max(products, key=mention_score, default=None)
    if named is not None and mention_score(named) > 0:
        return await build_context(session, named.id) or dict(EMPTY_CONTEXT)
    built_all = [
        built for product in products if (built := await build_context(session, product.id))
    ]
    if not built_all:
        return dict(EMPTY_CONTEXT)
    # Worst product first, so single-product phrasing still leads with what matters.
    built_all.sort(key=lambda c: len(c["oos_pins"]), reverse=True)
    context = dict(built_all[0])
    if len(built_all) > 1:
        context["product_name"] = "your products"
        context["portfolio"] = [
            {
                "product_id": c["product_id"],
                "product_name": c["product_name"],
                "in_stock": c["in_stock"],
                "total_pins": c["total_pins"],
                "oos_pins": c["oos_pins"],
                "avg_price": c["avg_price"],
                "cheapest_rival": c["cheapest_rival"],
                "price_gap_pins": c.get("price_gap_pins", 0),
            }
            for c in built_all
        ]
    return context


async def _usage_context(session: AsyncSession, user_id: str) -> dict:
    plan = (
        await session.scalar(select(Subscription.plan).where(Subscription.user_id == user_id))
    ) or "free"
    return {
        "plan": plan,
        "credits_used_today": await daily_credits_used(session, user_id),
        "daily_credit_budget": limits_for(plan).daily_credit_budget,
    }


def _message_payload(row: ChatMessage) -> ChatMessageOut:
    return ChatMessageOut(
        role=row.role,
        content=row.content,
        actions=row.actions or [],
        evidence=row.evidence or [],
        created_at=row.created_at,
    )


async def get_owned_conversation(
    session: AsyncSession, user: User, conversation_id: str
) -> ChatConversation:
    row = await session.scalar(
        select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == user.id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return row


async def _answer_message(
    session: AsyncSession, conversation: ChatConversation, content: str
) -> MessageResponse:
    message_count = await session.scalar(
        select(func.count(ChatMessage.id)).where(
            ChatMessage.conversation_id == conversation.id
        )
    )
    if (message_count or 0) >= MAX_MESSAGES_PER_CONVERSATION:
        raise HTTPException(
            status_code=422,
            detail=f"Conversation limit of {MAX_MESSAGES_PER_CONVERSATION} messages reached",
        )
    history_rows = list(
        (
            await session.scalars(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation.id)
                .order_by(ChatMessage.created_at.desc())
                .limit(HISTORY_WINDOW)
            )
        ).all()
    )
    history = [
        {"role": row.role, "content": row.content}
        for row in reversed(history_rows)
    ]
    context = dict(EMPTY_CONTEXT)
    if conversation.product_id:
        built = await build_context(session, conversation.product_id)
        if built is not None:
            context = built
    else:
        context = await _unfocused_context(session, conversation.user_id, content)
    context.update(await _usage_context(session, conversation.user_id))
    provider = get_ai_provider()
    result, source = await with_fallback(
        provider, "chat", context, content, history
    )
    user_message = ChatMessage(
        conversation_id=conversation.id,
        role="user",
        content=content,
    )
    assistant_message = ChatMessage(
        conversation_id=conversation.id,
        role="assistant",
        content=result.reply[:8000],
        actions=safe_actions([action.model_dump() for action in result.actions]),
        evidence=[item.model_dump() for item in result.evidence],
    )
    session.add(user_message)
    session.add(assistant_message)
    await session.commit()
    await session.refresh(assistant_message)
    reply = _message_payload(assistant_message)
    return MessageResponse(
        source=source,
        reply=reply,
        actions=reply.actions,
        evidence=reply.evidence,
    )


@router.get("/help/topics", response_model=HelpTopicListResponse)
async def get_help_topics() -> HelpTopicListResponse:
    return HelpTopicListResponse(
        items=[HelpTopic(**topic) for topic in list_help_topics()]
    )


@router.get("/help/topics/{slug}", response_model=HelpTopic)
async def get_help_topic_by_slug(slug: str) -> HelpTopic:
    topic = get_help_topic(slug)
    if topic is None:
        raise HTTPException(status_code=404, detail="Help topic not found")
    return HelpTopic(**topic)


@router.post("/chat/conversations", response_model=ConversationSummary)
async def create_conversation(
    payload: ConversationCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ConversationSummary:
    product_id: str | None = None
    title = payload.title
    if payload.product_id is not None:
        product = await get_owned_product(session, user.id, payload.product_id)
        product_id = product.id
        title = title or f"Chat about {product.name}"
    conversation = ChatConversation(
        user_id=user.id,
        product_id=product_id,
        title=title or "New chat",
    )
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return ConversationSummary(
        id=conversation.id,
        title=conversation.title,
        product_id=conversation.product_id,
        created_at=conversation.created_at,
        message_count=0,
    )


@router.get("/chat/conversations", response_model=ConversationListResponse)
async def list_conversations(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ConversationListResponse:
    counts = dict(
        (
            await session.execute(
                select(ChatMessage.conversation_id, func.count(ChatMessage.id))
                .join(
                    ChatConversation,
                    ChatConversation.id == ChatMessage.conversation_id,
                )
                .where(ChatConversation.user_id == user.id)
                .group_by(ChatMessage.conversation_id)
            )
        ).all()
    )
    rows = list(
        (
            await session.scalars(
                select(ChatConversation)
                .where(ChatConversation.user_id == user.id)
                .order_by(ChatConversation.created_at.desc())
            )
        ).all()
    )
    return ConversationListResponse(
        items=[
            ConversationSummary(
                id=row.id,
                title=row.title,
                product_id=row.product_id,
                created_at=row.created_at,
                message_count=counts.get(row.id, 0),
            )
            for row in rows
        ]
    )


@router.get("/chat/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ConversationDetail:
    conversation = await get_owned_conversation(session, user, conversation_id)
    messages = list(
        (
            await session.scalars(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation.id)
                .order_by(ChatMessage.created_at.asc())
            )
        ).all()
    )
    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        product_id=conversation.product_id,
        created_at=conversation.created_at,
        messages=[_message_payload(row) for row in messages],
    )


@router.post(
    "/chat/conversations/{conversation_id}/messages",
    response_model=MessageResponse,
)
async def post_message(
    conversation_id: str,
    payload: MessageCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MessageResponse:
    conversation = await get_owned_conversation(session, user, conversation_id)
    return await _answer_message(session, conversation, payload.content)


@router.post("/chat", response_model=ChatResponse)
async def post_chat(
    payload: ChatRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ChatResponse:
    """Single-shot chat: creates or continues a conversation and answers."""
    if payload.conversation_id is not None:
        conversation = await get_owned_conversation(
            session, user, payload.conversation_id
        )
    else:
        product_id: str | None = None
        # Name the conversation after its first question so history is scannable.
        first = " ".join(payload.message.split())
        title = first if len(first) <= 60 else first[:57].rstrip() + "…"
        if payload.product_id is not None:
            product = await get_owned_product(session, user.id, payload.product_id)
            product_id = product.id
            title = f"{product.name}: {title}"[:300]
        conversation = ChatConversation(
            user_id=user.id,
            product_id=product_id,
            title=title,
        )
        session.add(conversation)
        await session.commit()
        await session.refresh(conversation)
    message = await _answer_message(session, conversation, payload.message)
    return ChatResponse(
        conversation_id=conversation.id,
        answer=message.reply.content,
        actions=message.actions,
        evidence=message.evidence,
        source=message.source,
    )
