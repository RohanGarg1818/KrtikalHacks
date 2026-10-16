from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    database: str
    mock_mode: bool
    integrations: dict[str, bool]
    bot_running: bool
    scheduler_running: bool
