from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RunCreate(BaseModel):
    pincodes: list[str] | None = None
    platforms: list[str] | None = None


class RunCreated(BaseModel):
    run_id: str
    estimated_credits: int


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    product_id: str
    trigger: str
    status: str
    total_jobs: int
    done_jobs: int
    failed_jobs: int
    credits_used: int
    started_at: datetime | None
    finished_at: datetime | None
