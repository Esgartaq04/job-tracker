"""Insights (README §7.4). Aggregation happens in Python rather than SQL: the
volumes are personal-scale (hundreds of rows), and it keeps the same code path
working on both Postgres and SQLite."""

import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from src.core.deps import CurrentUser, DbSession
from src.models import Application, AppStatus, StatusEvent
from src.models.util import as_utc, utcnow
from src.schemas.stats import (
    FunnelOut,
    FunnelStage,
    SourceBreakdown,
    TimeInStage,
    VelocityBucket,
    VelocityOut,
)
from src.services.applications import compute_staleness, user_applications

router = APIRouter(prefix="/stats", tags=["stats"])

#: Stages the funnel reports, in pipeline order after `applied`.
FUNNEL_STAGES = [
    AppStatus.applied,
    AppStatus.oa,
    AppStatus.phone_screen,
    AppStatus.interview,
    AppStatus.final,
    AppStatus.offer,
]

#: Any of these means the company actually got back to you.
RESPONSE_STATUSES = {
    AppStatus.oa,
    AppStatus.phone_screen,
    AppStatus.interview,
    AppStatus.final,
    AppStatus.offer,
    AppStatus.rejected,
}


def _load(db, user_id, since: datetime | None, until: datetime | None):
    stmt = user_applications(user_id)
    if since:
        stmt = stmt.where(Application.saved_at >= since)
    if until:
        stmt = stmt.where(Application.saved_at <= until)
    applications = list(db.scalars(stmt).unique().all())

    if not applications:
        return [], {}

    ids = [row.id for row in applications]
    events_by_app: dict = defaultdict(list)
    for event in db.scalars(
        select(StatusEvent)
        .where(StatusEvent.application_id.in_(ids))
        .order_by(StatusEvent.occurred_at.asc())
    ).all():
        events_by_app[event.application_id].append(event)
    return applications, events_by_app


@router.get("/funnel", response_model=FunnelOut)
def funnel(
    user: CurrentUser,
    db: DbSession,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
) -> FunnelOut:
    applications, events_by_app = _load(db, user.id, from_, to)

    reached: dict[AppStatus, int] = {stage: 0 for stage in FUNNEL_STAGES}
    responded = 0
    first_response_days: list[float] = []

    for application in applications:
        history = events_by_app.get(application.id, [])
        seen = {event.to_status for event in history} | {application.status}

        for stage in FUNNEL_STAGES:
            if stage in seen:
                reached[stage] += 1

        if seen & RESPONSE_STATUSES:
            responded += 1

        applied_at = as_utc(application.applied_at)
        if applied_at:
            responses = [
                as_utc(event.occurred_at)
                for event in history
                if event.to_status in RESPONSE_STATUSES and as_utc(event.occurred_at) >= applied_at
            ]
            if responses:
                first_response_days.append((min(responses) - applied_at).days)

    applied_total = reached[AppStatus.applied]
    stages = [
        FunnelStage(
            status=stage,
            reached=reached[stage],
            conversion_from_applied=(
                round(reached[stage] / applied_total, 4) if applied_total else None
            ),
        )
        for stage in FUNNEL_STAGES
    ]

    return FunnelOut(
        total=len(applications),
        applied=applied_total,
        stages=stages,
        response_rate=round(responded / applied_total, 4) if applied_total else None,
        median_days_to_first_response=(
            round(statistics.median(first_response_days), 1) if first_response_days else None
        ),
    )


@router.get("/velocity", response_model=VelocityOut)
def velocity(
    user: CurrentUser,
    db: DbSession,
    weeks: Annotated[int, Query(ge=1, le=104)] = 12,
) -> VelocityOut:
    now = utcnow()
    window_start = now - timedelta(weeks=weeks)
    applications, events_by_app = _load(db, user.id, None, None)

    def week_key(moment: datetime) -> str:
        moment = as_utc(moment)
        monday = moment - timedelta(days=moment.weekday())
        return monday.date().isoformat()

    buckets: dict[str, dict[str, int]] = {}
    for offset in range(weeks):
        key = week_key(window_start + timedelta(weeks=offset))
        buckets[key] = {"saved": 0, "applied": 0}

    for application in applications:
        saved_at = as_utc(application.saved_at)
        if saved_at >= window_start:
            buckets.setdefault(week_key(saved_at), {"saved": 0, "applied": 0})["saved"] += 1
        applied_at = as_utc(application.applied_at)
        if applied_at and applied_at >= window_start:
            buckets.setdefault(week_key(applied_at), {"saved": 0, "applied": 0})["applied"] += 1

    # Time in stage: how long each application sat in a status before moving on.
    durations: dict[AppStatus, list[float]] = defaultdict(list)
    open_counts: dict[AppStatus, int] = defaultdict(int)
    for application in applications:
        history = events_by_app.get(application.id, [])
        for current, following in zip(history, history[1:], strict=False):
            delta = as_utc(following.occurred_at) - as_utc(current.occurred_at)
            durations[current.to_status].append(delta.total_seconds() / 86400)
        open_counts[application.status] += 1

    time_in_stage = [
        TimeInStage(
            status=status_,
            median_days=(
                round(statistics.median(durations[status_]), 1) if durations[status_] else None
            ),
            open_count=open_counts.get(status_, 0),
        )
        for status_ in AppStatus
        if durations[status_] or open_counts.get(status_)
    ]

    stale = sum(1 for application in applications if compute_staleness(application, now) != "none")

    return VelocityOut(
        weekly=[
            VelocityBucket(week_start=key, saved=value["saved"], applied=value["applied"])
            for key, value in sorted(buckets.items())
        ],
        time_in_stage=time_in_stage,
        stale_count=stale,
    )


@router.get("/sources", response_model=list[SourceBreakdown])
def sources(user: CurrentUser, db: DbSession) -> list[SourceBreakdown]:
    """Response rate by ATS — also the signal for "are my adapters still working?"."""
    applications, events_by_app = _load(db, user.id, None, None)

    totals: dict[str, int] = defaultdict(int)
    responded: dict[str, int] = defaultdict(int)
    for application in applications:
        vendor = application.ats_vendor or application.source_host or "unknown"
        totals[vendor] += 1
        seen = {event.to_status for event in events_by_app.get(application.id, [])} | {
            application.status
        }
        if seen & RESPONSE_STATUSES:
            responded[vendor] += 1

    return sorted(
        (
            SourceBreakdown(
                ats_vendor=vendor,
                total=count,
                responded=responded[vendor],
                response_rate=round(responded[vendor] / count, 4) if count else 0.0,
            )
            for vendor, count in totals.items()
        ),
        key=lambda row: row.total,
        reverse=True,
    )
