"""Authentication dependency. Stage 1 implements safe, deterministic development auth."""

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .db import get_session
from .models.user import User

DEMO_EMAIL = "riya@shelfsense.demo"
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User:
    if settings.dev_auth_enabled:
        user = await session.scalar(select(User).where(User.email == DEMO_EMAIL))
        if user is None:
            raise HTTPException(
                status_code=503,
                detail="Demo user is missing; run python -m scripts.seed",
            )
        return user

    if credentials is None:
        raise HTTPException(status_code=401, detail="Bearer token required")
    try:
        claims = jwt.decode(
            credentials.credentials,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid bearer token") from exc
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise HTTPException(status_code=401, detail="Bearer token has no subject")
    user = await session.get(User, subject)
    if user is None:
        user = User(
            id=subject,
            name=str(
                claims.get("user_metadata", {}).get("full_name") or "ShelfSense user"
            ),
            email=str(claims.get("email") or f"{subject}@supabase.local"),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user
