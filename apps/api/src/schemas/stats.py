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


class VelocityOut(BaseModel):
    weekly: list[VelocityBucket]
    stale_count: int


class FlowNode(BaseModel):
    #: An `AppStatus` value, or `no_reply` for applications still waiting on a first answer.
    id: str
    label: str
    value: int


class FlowLink(BaseModel):
    source: str
    target: str
    value: int


class FlowOut(BaseModel):
    total_applied: int
    nodes: list[FlowNode]
    links: list[FlowLink]


class ActivityDay(BaseModel):
    date: str
    count: int


class ActivityOut(BaseModel):
    days: list[ActivityDay]
    current_streak: int
    longest_streak: int
    this_week: int
