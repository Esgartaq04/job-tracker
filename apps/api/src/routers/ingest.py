import uuid

from fastapi import APIRouter, HTTPException, status

from src.core.deps import CurrentUser, DbSession
from src.models import Application, AppStatus, EventSource, IngestStatus, User
from src.models.util import utcnow
from src.schemas.application import ApplicationDetailOut
from src.schemas.ingest import (
    IngestAccepted,
    IngestBatchAccepted,
    IngestBatchRequest,
    IngestFromDomRequest,
    IngestFromTextRequest,
    IngestRequest,
)
from src.services import events, ranking
from src.services.applications import get_owned, to_out, user_applications
from src.services.ingestion import pipeline, queue
from src.services.ingestion.normalize import (
    canonicalize,
    company_domain_for,
    company_guess_from_url,
    host_of,
    normalize_url,
)
from src.services.transitions import apply_transition, record_initial_event

router = APIRouter(prefix="/ingest", tags=["ingest"])

#: Re-ingestion hangs off the application resource, per the API surface in README §6.
application_router = APIRouter(prefix="/applications", tags=["ingest"])


def _provisional(
    db: DbSession, user: User, url: str, *, mark_as_applied: bool
) -> tuple[Application, bool]:
    """Create the card that appears on the board instantly, or return the existing
    one when this URL is already tracked (README §4.2)."""
    try:
        normalized = normalize_url(url)
        canonical = canonicalize(url)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    existing = db.scalar(user_applications(user.id).where(Application.canonical_url == canonical))
    if existing is not None:
        return existing, True

    board_status = AppStatus.applied if mark_as_applied else AppStatus.saved
    application = Application(
        user_id=user.id,
        source_url=normalized,
        canonical_url=canonical,
        source_host=host_of(normalized),
        company_domain=company_domain_for(normalized),
        company=company_guess_from_url(normalized),
        title="Untitled",
        status=board_status,
        applied_at=utcnow() if mark_as_applied else None,
        ingest_status=IngestStatus.pending,
        board_position=ranking.top_position(db, user.id, board_status),
        # Both are placeholders until a tier resolves; the pipeline may replace them.
        extraction_meta={"guessed": ["company", "title"]},
    )
    db.add(application)
    db.flush()
    record_initial_event(db, application, source=EventSource.manual)
    db.flush()
    return application, False


@router.post("", response_model=IngestAccepted, status_code=status.HTTP_202_ACCEPTED)
def ingest_url(payload: IngestRequest, user: CurrentUser, db: DbSession) -> IngestAccepted:
    """Returns immediately with a provisional record; the worker fills it in and
    streams progress over /events."""
    application, duplicate = _provisional(
        db, user, payload.url, mark_as_applied=payload.mark_as_applied
    )
    db.commit()

    if not duplicate:
        events.publish(user.id, "application.created", {"application_id": str(application.id)})
        queue.enqueue_ingest(application.id)

    return IngestAccepted(
        application_id=application.id,
        ingest_status=application.ingest_status,
        duplicate=duplicate,
    )


@router.post("/batch", response_model=IngestBatchAccepted, status_code=status.HTTP_202_ACCEPTED)
def ingest_batch(
    payload: IngestBatchRequest, user: CurrentUser, db: DbSession
) -> IngestBatchAccepted:
    """Multi-line paste in the quick-add bar."""
    accepted: list[IngestAccepted] = []
    fresh: list[uuid.UUID] = []

    for url in payload.urls:
        if not url.strip():
            continue
        application, duplicate = _provisional(
            db, user, url, mark_as_applied=payload.mark_as_applied
        )
        accepted.append(
            IngestAccepted(
                application_id=application.id,
                ingest_status=application.ingest_status,
                duplicate=duplicate,
            )
        )
        if not duplicate:
            fresh.append(application.id)

    db.commit()
    for application_id in fresh:
        events.publish(user.id, "application.created", {"application_id": str(application_id)})
        queue.enqueue_ingest(application_id)

    return IngestBatchAccepted(accepted=accepted)


@router.post("/from-dom", response_model=ApplicationDetailOut)
def ingest_from_dom(
    payload: IngestFromDomRequest, user: CurrentUser, db: DbSession
) -> ApplicationDetailOut:
    """Browser-extension path: the user's own browser already rendered the page, so
    we parse the DOM they POST instead of scraping the site (README §4.1)."""
    application, _ = _provisional(db, user, payload.url, mark_as_applied=payload.mark_as_applied)
    outcome = pipeline.run_pipeline(application.source_url, html=payload.html)
    pipeline.apply_outcome(db, application, outcome)
    db.commit()

    events.publish(
        user.id,
        "ingest.completed",
        {"application_id": str(application.id), "ingest_status": application.ingest_status.value},
    )
    return to_out(application, detail=True)


@router.post("/from-text", response_model=ApplicationDetailOut)
def ingest_from_text(
    payload: IngestFromTextRequest, user: CurrentUser, db: DbSession
) -> ApplicationDetailOut:
    """Tier 5 — always reachable. A record is never blocked on ingestion."""
    url = payload.url or f"manual:{uuid.uuid4()}"
    if payload.url:
        application, _ = _provisional(
            db, user, payload.url, mark_as_applied=payload.mark_as_applied
        )
    else:
        board_status = AppStatus.applied if payload.mark_as_applied else AppStatus.saved
        application = Application(
            user_id=user.id,
            source_url=url,
            canonical_url=url,
            status=board_status,
            title="Untitled",
            applied_at=utcnow() if payload.mark_as_applied else None,
            ingest_status=IngestStatus.pending,
            board_position=ranking.top_position(db, user.id, board_status),
        )
        db.add(application)
        db.flush()
        record_initial_event(db, application)

    outcome = pipeline.run_pipeline(application.source_url, text=payload.text)
    pipeline.apply_outcome(db, application, outcome, mark_manual=True)

    # Applied last: what the user typed outranks anything the fallback inferred.
    if payload.company:
        application.company = payload.company
    if payload.title:
        application.title = payload.title
    db.commit()
    return to_out(application, detail=True)


@application_router.post("/{application_id}/reingest", response_model=ApplicationDetailOut)
def reingest(application_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ApplicationDetailOut:
    """Re-run the pipeline. `description_raw` is never overwritten — the archived
    copy is often all that survives once a posting is taken down."""
    application = get_owned(db, user.id, application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such application")

    application.ingest_status = IngestStatus.pending
    db.commit()
    queue.enqueue_ingest(application.id)
    return to_out(application, detail=True)


@application_router.post("/{application_id}/mark-applied", response_model=ApplicationDetailOut)
def mark_applied(
    application_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> ApplicationDetailOut:
    """ "Paste & mark as applied" for case 2 in README §2 — sets both timestamps."""
    application = get_owned(db, user.id, application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such application")

    apply_transition(db, application, AppStatus.applied)
    application.board_position = ranking.top_position(db, user.id, AppStatus.applied)
    db.commit()
    return to_out(application, detail=True)
