"""Authentication dependencies: development demo user or Supabase-issued JWTs."""

import jwt
from fastapi import Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .db import SessionLocal, get_session
from .models.user import User

DEMO_EMAIL = "riya@shelfsense.demo"
bearer_scheme = HTTPBearer(auto_error=False)


def decode_supabase_token(token: str, secret: str) -> dict:
    """Validate a Supabase access token; `exp` and `sub` are mandatory."""
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience="authenticated",
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid bearer token") from exc
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise HTTPException(status_code=401, detail="Bearer token has no subject")
    return claims


async def provision_user(session: AsyncSession, claims: dict) -> User:
    """Return the local user for a token subject, creating it on first sight."""
    subject: str = claims["sub"]
    user = await session.get(User, subject)
    if user is not None:
        return user
    email = claims.get("email")
    email = email.strip().lower() if isinstance(email, str) and email.strip() else None
    if email is not None:
        owner = await session.scalar(select(User.id).where(User.email == email))
        if owner is not None:
            raise HTTPException(
                status_code=409,
                detail="Another account already uses this email address",
            )
    metadata = claims.get("user_metadata")
    full_name = metadata.get("full_name") if isinstance(metadata, dict) else None
    user = User(
        id=subject,
        name=str(full_name).strip()[:200] if full_name else "ShelfSense user",
        email=email or f"{subject}@supabase.local",
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        # A concurrent first request for the same subject won the insert.
        await session.rollback()
        user = await session.get(User, subject)
        if user is None:
            raise HTTPException(
                status_code=409,
                detail="Another account already uses this email address",
            ) from None
        return user
    await session.refresh(user)
    return user


async def resolve_user(
    session: AsyncSession, settings: Settings, token: str | None
) -> User:
    if settings.dev_auth_enabled:
        user = await session.scalar(select(User).where(User.email == DEMO_EMAIL))
        if user is None:
            raise HTTPException(
                status_code=503,
                detail="Demo user is missing; run python -m scripts.seed",
            )
        return user
    if not settings.supabase_jwt_secret:
        # Production without a secret is refused at startup; never fail open here.
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token required")
    claims = decode_supabase_token(token, settings.supabase_jwt_secret)
    return await provision_user(session, claims)


async def get_current_user(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User:
    return await resolve_user(
        session, settings, credentials.credentials if credentials else None
    )


async def get_stream_user(
    settings: Settings = Depends(get_settings),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    access_token: str | None = Query(default=None, max_length=4096),
) -> User:
    """Auth for long-lived SSE responses.

    `EventSource` cannot set headers, so `?access_token=` is accepted as well.
    The lookup uses its own short session so no connection is held for the
    lifetime of the stream.
    """
    token = credentials.credentials if credentials else access_token
    async with SessionLocal() as session:
        return await resolve_user(session, settings, token)
