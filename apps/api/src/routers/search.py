from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from src.core.deps import CurrentUser, DbSession
from src.models import Application, Tag
from src.schemas.application import ApplicationOut, TagOut
from src.services.applications import apply_text_filter, to_out, user_applications

router = APIRouter(tags=["search"])


@router.get("/search", response_model=list[ApplicationOut])
def search(
    user: CurrentUser,
    db: DbSession,
    q: Annotated[str, Query(min_length=1)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[ApplicationOut]:
    """Full-text on Postgres (the generated `search_vector` column), LIKE on SQLite."""
    stmt = apply_text_filter(user_applications(user.id), q).order_by(Application.updated_at.desc())
    rows = db.scalars(stmt.limit(limit)).unique().all()
    return [to_out(row) for row in rows]


@router.get("/tags", response_model=list[TagOut])
def list_tags(user: CurrentUser, db: DbSession) -> list[Tag]:
    return list(db.scalars(select(Tag).where(Tag.user_id == user.id).order_by(Tag.name)).all())
