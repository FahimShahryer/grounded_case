from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models.enums import LlmPurpose


class LlmCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: int | None
    purpose: LlmPurpose
    model: str
    prompt_hash: str
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: Decimal | None
    latency_ms: int | None
    cache_hit: bool
    success: bool
    error: str | None
    created_at: datetime
