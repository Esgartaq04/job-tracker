import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status

from src.core.deps import CurrentUser, DbSession
from src.schemas.cover_letter import CoverLetterOut, CoverLetterUpdate
from src.services import ai, cover_letters
from src.services.ai_errors import ai_errors
from src.services.applications import get_owned

router = APIRouter(prefix="/applications", tags=["cover letters"])

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _application(db: DbSession, user: CurrentUser, application_id: uuid.UUID):
    application = get_owned(db, user.id, application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such application")
    return application


@router.post("/{application_id}/cover-letter", response_model=CoverLetterOut)
def generate_cover_letter(
    application_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    resume: Annotated[UploadFile, File(description="Your resume, PDF or .docx. Not stored.")],
    notes: Annotated[str | None, Form()] = None,
) -> CoverLetterOut:
    """Write (or rewrite) this listing's cover letter from its cleaned description and
    the uploaded resume. The resume is read for this call and discarded."""
    application = _application(db, user, application_id)
    # One byte past the cap is enough to know it's too big without reading it all.
    data = resume.file.read(ai.MAX_RESUME_BYTES + 1)

    with ai_errors():
        try:
            letter = cover_letters.generate(
                db, application, data, filename=resume.filename, notes=notes
            )
        except cover_letters.NotReady as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    return CoverLetterOut.model_validate(letter)


@router.get("/{application_id}/cover-letter", response_model=CoverLetterOut)
def get_cover_letter(application_id: uuid.UUID, user: CurrentUser, db: DbSession) -> CoverLetterOut:
    letter = cover_letters.owned_letter(db, user.id, _application(db, user, application_id))
    if letter is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No cover letter yet")
    return CoverLetterOut.model_validate(letter)


@router.patch("/{application_id}/cover-letter", response_model=CoverLetterOut)
def edit_cover_letter(
    application_id: uuid.UUID, payload: CoverLetterUpdate, user: CurrentUser, db: DbSession
) -> CoverLetterOut:
    letter = cover_letters.owned_letter(db, user.id, _application(db, user, application_id))
    if letter is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No cover letter yet")
    letter.content = payload.content
    db.commit()
    return CoverLetterOut.model_validate(letter)


@router.get("/{application_id}/cover-letter.docx")
def download_cover_letter(application_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    application = _application(db, user, application_id)
    letter = cover_letters.owned_letter(db, user.id, application)
    if letter is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No cover letter yet")

    name = cover_letters.download_name(application)
    return Response(
        content=cover_letters.docx_bytes(letter.content or ""),
        media_type=DOCX_TYPE,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )
