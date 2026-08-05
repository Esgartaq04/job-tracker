"""Fractional index maths for board ordering (README §5.1).

Dropping a card between neighbours `a` and `b` sets `position = (a + b) / 2`, which
makes a reorder a single-row UPDATE. Floats lose precision after ~50 subdivisions
between the same pair, so `needs_respacing` flags a column for the re-spacing sweep.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Application, AppStatus

#: Gap used when appending to the end of a column.
STEP = 1024.0

#: Below this gap the float mantissa is close enough to exhausted that we re-space.
MIN_GAP = 1e-6


def position_between(before: float | None, after: float | None) -> float:
    """`before` is the neighbour above (smaller position), `after` the one below."""
    if before is None and after is None:
        return STEP
    if before is None:
        return after - STEP
    if after is None:
        return before + STEP
    return (before + after) / 2.0


def needs_respacing(before: float | None, after: float | None) -> bool:
    if before is None or after is None:
        return False
    return abs(after - before) < MIN_GAP


def next_position(db: Session, user_id: uuid.UUID, status: AppStatus) -> float:
    """Position for a card appended to the bottom of a column."""
    current_max = db.scalar(
        select(Application.board_position)
        .where(
            Application.user_id == user_id,
            Application.status == status,
            Application.archived_at.is_(None),
        )
        .order_by(Application.board_position.desc())
        .limit(1)
    )
    return STEP if current_max is None else current_max + STEP


def top_position(db: Session, user_id: uuid.UUID, status: AppStatus) -> float:
    """Position for a card prepended to the top of a column (new pastes land here)."""
    current_min = db.scalar(
        select(Application.board_position)
        .where(
            Application.user_id == user_id,
            Application.status == status,
            Application.archived_at.is_(None),
        )
        .order_by(Application.board_position.asc())
        .limit(1)
    )
    return STEP if current_min is None else current_min - STEP


def respace_column(db: Session, user_id: uuid.UUID, status: AppStatus) -> None:
    """Rewrite a column's positions onto a clean STEP grid, preserving order."""
    rows = (
        db.scalars(
            select(Application)
            .where(
                Application.user_id == user_id,
                Application.status == status,
                Application.archived_at.is_(None),
            )
            .order_by(Application.board_position.asc(), Application.created_at.asc())
        )
        .unique()
        .all()
    )
    for index, row in enumerate(rows, start=1):
        row.board_position = index * STEP
    db.flush()


def resolve_move_position(
    db: Session,
    user_id: uuid.UUID,
    to_status: AppStatus,
    before_id: uuid.UUID | None,
    after_id: uuid.UUID | None,
    moving_id: uuid.UUID | None = None,
) -> tuple[float, bool]:
    """Translate neighbour ids into a position.

    Returns `(position, should_respace)`. Neighbours that don't exist, are archived,
    or live in another column are ignored rather than rejected — a stale client should
    still land the card somewhere sane.
    """

    def _position_of(candidate: uuid.UUID | None) -> float | None:
        if candidate is None or candidate == moving_id:
            return None
        row = db.get(Application, candidate)
        if (
            row is None
            or row.user_id != user_id
            or row.archived_at is not None
            or row.status != to_status
        ):
            return None
        return row.board_position

    before = _position_of(before_id)
    after = _position_of(after_id)

    if before is None and after is None:
        # No usable neighbours: bottom of the column unless the client asked for the top.
        if after_id is not None:
            return top_position(db, user_id, to_status), False
        return next_position(db, user_id, to_status), False

    return position_between(before, after), needs_respacing(before, after)
