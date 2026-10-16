"""Screenshot storage: Supabase Storage when configured, local disk otherwise.

Local files land in ``./media/screenshots`` and are served by the app at
``/media/...``. Any Supabase failure falls back to local storage so a run never
loses its evidence.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from uuid import uuid4

import httpx

from ..config import Settings, get_settings

logger = logging.getLogger("shelfsense.storage")

LOCAL_BASE = Path("media") / "screenshots"


async def save_screenshot(
    data: bytes, *, product_id: str, platform: str, pincode: str
) -> str:
    settings = get_settings()
    name = f"{platform}_{pincode}_{uuid4().hex[:12]}.png"
    path = f"{product_id}/{name}"
    if settings.storage_enabled:
        uploaded = await _upload_supabase(settings, data, path)
        if uploaded is not None:
            return uploaded
        logger.warning("Supabase upload failed; saving screenshot locally instead")
    return await _save_local(data, path)


async def _save_local(data: bytes, path: str) -> str:
    target = LOCAL_BASE / path

    def write() -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    await asyncio.to_thread(write)
    return f"/media/screenshots/{path}"


async def _upload_supabase(
    settings: Settings, data: bytes, path: str
) -> str | None:
    # TODO(supabase): confirm the Storage object endpoint and public URL format.
    endpoint = (
        f"{settings.supabase_url}/storage/v1/object/"
        f"{settings.supabase_storage_bucket}/{path}"
    )
    headers = {
        "Authorization": f"Bearer {settings.supabase_service_key}",
        "apikey": settings.supabase_service_key,
        "Content-Type": "image/png",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                endpoint, params={"upsert": "true"}, content=data, headers=headers
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Supabase storage upload failed: %s", exc)
        return None
    return f"{settings.supabase_url}/storage/v1/object/public/{settings.supabase_storage_bucket}/{path}"
