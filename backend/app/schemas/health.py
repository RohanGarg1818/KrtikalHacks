from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    database: str
    mock_mode: bool
    integrations: dict[str, bool]
    auth_mode: Literal["dev", "supabase"]
    tinyfish_mode: Literal["live", "simulated"]
    bot_running: bool
    scheduler_running: bool
