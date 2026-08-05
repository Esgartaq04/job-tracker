from pydantic import BaseModel

from src.models.enums import AppStatus


class FunnelStage(BaseModel):
    status: AppStatus
    reached: int
    conversion_from_applied: float | None = None


class FunnelOut(BaseModel):
    total: int
    applied: int
    stages: list[FunnelStage]
    response_rate: float | None = None
    median_days_to_first_response: float | None = None


class VelocityBucket(BaseModel):
    week_start: str
    saved: int
    applied: int


class TimeInStage(BaseModel):
    status: AppStatus
    median_days: float | None
    open_count: int


class VelocityOut(BaseModel):
    weekly: list[VelocityBucket]
    time_in_stage: list[TimeInStage]
    stale_count: int


class SourceBreakdown(BaseModel):
    ats_vendor: str
    total: int
    responded: int
    response_rate: float
