"""Insights (README §7.4). Aggregation happens in Python rather than SQL: the
volumes are personal-scale (hundreds of rows), and it keeps the same code path
working on both Postgres and SQLite."""

import statistics
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Query
from sqlalchemy import select

from src.core.deps import CurrentUser, DbSession
from src.models import Application, AppStatus, StatusEvent
from src.models.util import as_utc, utcnow
from src.schemas.stats import (
    ActivityDay,
    ActivityOut,
    FlowLink,
    FlowNode,
    FlowOut,
    FunnelOut,
    FunnelStage,
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

#: Outcomes that end a path in the flow diagram.
TERMINAL_OUTCOMES = [AppStatus.rejected, AppStatus.ghosted, AppStatus.withdrawn]

#: You can't be rejected or ghosted without having applied, even if the card skipped
#: the Applied column on its way there.
IMPLIES_APPLIED = set(FUNNEL_STAGES) | {AppStatus.rejected, AppStatus.ghosted}

NO_REPLY = "no_reply"

FLOW_LABELS = {
    AppStatus.applied: "Applied",
    AppStatus.oa: "OA",
    AppStatus.phone_screen: "Phone screen",
    AppStatus.interview: "Interview",
    AppStatus.final: "Final",
    AppStatus.offer: "Offer",
    AppStatus.rejected: "Rejected",
    AppStatus.ghosted: "Ghosted",
    AppStatus.withdrawn: "Withdrawn",
    NO_REPLY: "No reply yet",
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

    stale = sum(1 for application in applications if compute_staleness(application, now) != "none")

    return VelocityOut(
        weekly=[
            VelocityBucket(week_start=key, saved=value["saved"], applied=value["applied"])
            for key, value in sorted(buckets.items())
        ],
        stale_count=stale,
    )


def flow_path(seen: set[AppStatus], current: AppStatus, applied: bool) -> list[str]:
    """The stages one application passed through, for the flow diagram.

    Backward moves are ignored: a card dragged from Interview back to Phone screen
    still counts as having reached Interview. Applications never applied to have no
    path at all.
    """
    if not (applied or seen & IMPLIES_APPLIED):
        return []

    path: list[str] = [AppStatus.applied.value]
    path += [stage.value for stage in FUNNEL_STAGES[1:] if stage in seen]
    if current in TERMINAL_OUTCOMES:
        path.append(current.value)
    elif len(path) == 1:
        path.append(NO_REPLY)
    return path


@router.get("/flow", response_model=FlowOut)
def flow(user: CurrentUser, db: DbSession) -> FlowOut:
    """Where applications went after being sent — the data behind the Sankey diagram."""
    applications, events_by_app = _load(db, user.id, None, None)

    links: Counter[tuple[str, str]] = Counter()
    total_applied = 0
    for application in applications:
        seen = {event.to_status for event in events_by_app.get(application.id, [])} | {
            application.status
        }
        path = flow_path(seen, application.status, application.applied_at is not None)
        if not path:
            continue
        total_applied += 1
        links.update(zip(path, path[1:], strict=False))

    # A node's size is whichever is larger of what flowed in and what flowed out. Every
    # path has at least two steps, so `applied`'s outflow is the total.
    inflow: Counter[str] = Counter()
    outflow: Counter[str] = Counter()
    for (source, target), count in links.items():
        outflow[source] += count
        inflow[target] += count
    nodes = [
        FlowNode(id=node_id, label=label, value=max(inflow[node_id], outflow[node_id]))
        for node_id, label in FLOW_LABELS.items()
        if inflow[node_id] or outflow[node_id]
    ]

    order = list(FLOW_LABELS)
    return FlowOut(
        total_applied=total_applied,
        nodes=nodes,
        links=[
            FlowLink(source=source, target=target, value=count)
            for (source, target), count in sorted(
                links.items(), key=lambda item: (order.index(item[0][0]), order.index(item[0][1]))
            )
        ],
    )


def compute_streaks(days: set[date], today: date) -> tuple[int, int]:
    """(current, longest) runs of consecutive days with at least one application.

    The current streak survives until the end of today: applying yesterday but not
    yet today still counts, so the number doesn't reset every morning.
    """
    longest = 0
    run = 0
    previous: date | None = None
    for day in sorted(days):
        run = run + 1 if previous and day - previous == timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day

    current = 0
    cursor = today if today in days else today - timedelta(days=1)
    while cursor in days:
        current += 1
        cursor -= timedelta(days=1)
    return current, longest


def _zone(name: str | None) -> ZoneInfo | type[UTC]:
    if not name:
        return UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


@router.get("/activity", response_model=ActivityOut)
def activity(
    user: CurrentUser,
    db: DbSession,
    days: Annotated[int, Query(ge=7, le=371)] = 182,
    tz: Annotated[str | None, Query(max_length=64)] = None,
) -> ActivityOut:
    """Applications per local calendar day, for the heatmap, streaks and weekly goal."""
    zone = _zone(tz)
    applications, _ = _load(db, user.id, None, None)

    per_day: Counter[date] = Counter(
        as_utc(application.applied_at).astimezone(zone).date()
        for application in applications
        if application.applied_at
    )

    today = utcnow().astimezone(zone).date()
    first = today - timedelta(days=days - 1)
    monday = today - timedelta(days=today.weekday())
    current, longest = compute_streaks(set(per_day), today)

    return ActivityOut(
        days=[
            ActivityDay(
                date=(first + timedelta(days=offset)).isoformat(),
                count=per_day[first + timedelta(days=offset)],
            )
            for offset in range(days)
        ],
        current_streak=current,
        longest_streak=longest,
        this_week=sum(count for day, count in per_day.items() if monday <= day <= today),
    )
