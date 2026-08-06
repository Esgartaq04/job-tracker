import uuid
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, select

from src.core.deps import CurrentUser, DbSession
from src.models import (
    BOARD_ORDER,
    Application,
    AppStatus,
    EventSource,
    IngestStatus,
    StatusEvent,
    Tag,
)
from src.models.util import utcnow
from src.schemas.application import (
    ApplicationCreate,
    ApplicationDetailOut,
    ApplicationOut,
    ApplicationUpdate,
    BoardColumn,
    BoardOut,
    ImportReportOut,
    MoveRequest,
    NoteCreate,
    PageOut,
    StatusEventOut,
)
from src.services import csv_import, events, ranking
from src.services.applications import (
    apply_text_filter,
    get_owned,
    resolve_tags,
    to_out,
    user_applications,
)
from src.services.ingestion.normalize import canonicalize, host_of
from src.services.transitions import apply_transition, record_initial_event

router = APIRouter(prefix="/applications", tags=["applications"])

#: Cap per column so a 500-card `Rejected` column doesn't ship 500 rows on first load;
#: the client virtualizes and pages the rest through /applications.
BOARD_PAGE_SIZE = 200


@router.get("/board", response_model=BoardOut)
def get_board(
    user: CurrentUser,
    db: DbSession,
    tag: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
) -> BoardOut:
    stmt = user_applications(user.id).order_by(Application.board_position.asc())
    if q:
        stmt = apply_text_filter(stmt, q)
    if tag:
        stmt = stmt.join(Application.tags).where(Tag.name == tag)

    rows = db.scalars(stmt).unique().all()

    grouped: dict[AppStatus, list[Application]] = {status_: [] for status_ in BOARD_ORDER}
    for row in rows:
        grouped[row.status].append(row)

    return BoardOut(
        columns=[
            BoardColumn(
                status=status_,
                count=len(items),
                items=[to_out(item) for item in items[:BOARD_PAGE_SIZE]],
            )
            for status_, items in grouped.items()
        ]
    )


@router.get("", response_model=PageOut)
def list_applications(
    user: CurrentUser,
    db: DbSession,
    status_filter: Annotated[AppStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query()] = None,
    tag: Annotated[str | None, Query()] = None,
    sort: Annotated[str, Query()] = "-saved_at",
    cursor: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    include_archived: Annotated[bool, Query()] = False,
) -> PageOut:
    stmt = user_applications(user.id, include_archived=include_archived)
    if status_filter:
        stmt = stmt.where(Application.status == status_filter)
    if q:
        stmt = apply_text_filter(stmt, q)
    if tag:
        stmt = stmt.join(Application.tags).where(Tag.name == tag)

    sort_field = sort.lstrip("-")
    column = {
        "saved_at": Application.saved_at,
        "applied_at": Application.applied_at,
        "company": Application.company,
        "title": Application.title,
        "updated_at": Application.updated_at,
        "priority": Application.priority,
    }.get(sort_field, Application.saved_at)
    stmt = stmt.order_by(column.desc() if sort.startswith("-") else column.asc())

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.offset(cursor).limit(limit)).unique().all()
    next_cursor = str(cursor + limit) if cursor + limit < total else None

    return PageOut(items=[to_out(row) for row in rows], next_cursor=next_cursor, total=total)


@router.post("", response_model=ApplicationDetailOut, status_code=status.HTTP_201_CREATED)
def create_application(
    payload: ApplicationCreate, user: CurrentUser, db: DbSession
) -> ApplicationOut:
    """Fully manual create — the Phase 1 path. A URL is optional here."""
    source_url = (payload.source_url or "").strip()
    canonical = canonicalize(source_url) if source_url else f"manual:{uuid.uuid4()}"

    if source_url:
        existing = db.scalar(
            user_applications(user.id).where(Application.canonical_url == canonical)
        )
        if existing is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {"message": "Already tracked", "application_id": str(existing.id)},
            )

    application = Application(
        user_id=user.id,
        source_url=source_url or canonical,
        canonical_url=canonical,
        source_host=host_of(source_url) if source_url else None,
        company=payload.company,
        title=payload.title or "Untitled",
        location=payload.location,
        is_remote=payload.is_remote,
        employment_type=payload.employment_type,
        description_user=payload.description,
        notes=payload.notes,
        status=payload.status,
        applied_at=payload.applied_at,
        ingest_status=IngestStatus.ok,
        board_position=ranking.top_position(db, user.id, payload.status),
    )
    if payload.status == AppStatus.applied and application.applied_at is None:
        application.applied_at = utcnow()
    application.tags = resolve_tags(db, user.id, payload.tags)

    db.add(application)
    db.flush()
    record_initial_event(db, application)
    db.flush()

    events.publish(user.id, "application.created", {"application_id": str(application.id)})
    return to_out(application, detail=True)


#: Declared before the `/{application_id}` routes: a path parameter matches any string
#: at routing time, so a later /import would be shadowed and answer 405.
#: Spreadsheets are big but not unbounded; this keeps a stray upload from eating memory.
MAX_IMPORT_BYTES = 5 * 1024 * 1024


@router.post("/import", response_model=ImportReportOut)
async def import_applications(
    user: CurrentUser,
    db: DbSession,
    file: Annotated[UploadFile, File(description="CSV export from a spreadsheet")],
) -> ImportReportOut:
    """Bring an existing spreadsheet onto the board.

    Headers are matched loosely (company/employer, role/title, link/url, …) because the
    templates people copy from each other never agree. Identity is not guessed: a row
    with neither a company nor a title is skipped and reported.
    """
    content = await file.read(MAX_IMPORT_BYTES + 1)
    if len(content) > MAX_IMPORT_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"That file is over {MAX_IMPORT_BYTES // (1024 * 1024)}MB",
        )
    if not content.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That file is empty")

    report = csv_import.import_csv(db, user.id, content)
    db.flush()

    if report.created:
        events.publish(user.id, "application.created", {"imported": report.created})

    return ImportReportOut(
        summary=report.summary,
        created=report.created,
        duplicates=report.duplicates,
        skipped=report.skipped,
        unmapped_columns=report.unmapped_columns,
    )


@router.get("/{application_id}", response_model=ApplicationDetailOut)
def get_application(application_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ApplicationOut:
    application = get_owned(db, user.id, application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such application")
    return to_out(application, detail=True)


@router.patch("/{application_id}", response_model=ApplicationDetailOut)
def update_application(
    application_id: uuid.UUID,
    payload: ApplicationUpdate,
    user: CurrentUser,
    db: DbSession,
) -> ApplicationOut:
    application = get_owned(db, user.id, application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such application")

    data = payload.model_dump(exclude_unset=True)
    tags = data.pop("tags", None)
    new_status = data.pop("status", None)

    for field, value in data.items():
        setattr(application, field, value)

    if tags is not None:
        application.tags = resolve_tags(db, user.id, tags)

    if new_status is not None and new_status != application.status:
        apply_transition(db, application, new_status, source=EventSource.manual)
        application.board_position = ranking.top_position(db, user.id, new_status)

    application.updated_at = utcnow()
    db.flush()

    events.publish(user.id, "application.updated", {"application_id": str(application.id)})
    return to_out(application, detail=True)


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_application(application_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    """Soft delete — sets `archived_at`, which also frees the canonical-URL index."""
    application = get_owned(db, user.id, application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such application")
    application.archived_at = utcnow()
    db.flush()
    events.publish(user.id, "application.archived", {"application_id": str(application.id)})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{application_id}/move", response_model=ApplicationDetailOut)
def move_application(
    application_id: uuid.UUID,
    payload: MoveRequest,
    user: CurrentUser,
    db: DbSession,
) -> ApplicationOut:
    """The server owns ranking: the client sends neighbour ids, never a position."""
    application = get_owned(db, user.id, application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such application")

    position, should_respace = ranking.resolve_move_position(
        db,
        user.id,
        payload.to_status,
        payload.before_id,
        payload.after_id,
        moving_id=application.id,
    )

    apply_transition(
        db, application, payload.to_status, source=EventSource.manual, note=payload.note
    )
    application.board_position = position
    db.flush()

    if should_respace:
        # Float precision has degraded between these two neighbours; rewrite the
        # column onto a clean grid before the next drop lands on the same pair.
        ranking.respace_column(db, user.id, payload.to_status)

    db.flush()
    events.publish(
        user.id,
        "application.moved",
        {"application_id": str(application.id), "status": application.status.value},
    )
    return to_out(application, detail=True)


@router.get("/{application_id}/events", response_model=list[StatusEventOut])
def list_status_events(
    application_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> list[StatusEvent]:
    application = get_owned(db, user.id, application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such application")
    return list(
        db.scalars(
            select(StatusEvent)
            .where(StatusEvent.application_id == application.id)
            .order_by(StatusEvent.occurred_at.asc())
        ).all()
    )


@router.post("/{application_id}/notes", response_model=ApplicationDetailOut)
def append_note(
    application_id: uuid.UUID, payload: NoteCreate, user: CurrentUser, db: DbSession
) -> ApplicationOut:
    application = get_owned(db, user.id, application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such application")

    stamp = utcnow().strftime("%Y-%m-%d")
    entry = f"{stamp} — {payload.text.strip()}"
    application.notes = f"{application.notes}\n{entry}" if application.notes else entry
    application.updated_at = utcnow()
    db.flush()
    return to_out(application, detail=True)
