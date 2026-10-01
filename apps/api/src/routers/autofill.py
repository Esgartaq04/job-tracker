from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from src.core.deps import CurrentUser, DbSession
from src.schemas.autofill import AutofillPlan, AutofillRequest, ResumeProfile
from src.services import ai, autofill
from src.services.ai_errors import ai_errors

router = APIRouter(prefix="/autofill", tags=["autofill"])


@router.post("/profile", response_model=ResumeProfile)
def read_resume(
    user: CurrentUser,
    db: DbSession,
    resume: Annotated[UploadFile, File(description="PDF or .docx. Read once, not stored.")],
) -> ResumeProfile:
    """The extension's first step: what the resume says, as fields a form can use.
    The profile goes back to the extension, which keeps it in memory; nothing is saved."""
    data = resume.file.read(ai.MAX_RESUME_BYTES + 1)
    with ai_errors():
        profile = autofill.read_profile(db, user.id, data, resume.filename)
    db.commit()
    return profile


@router.post("/map", response_model=AutofillPlan)
def map_fields(payload: AutofillRequest, user: CurrentUser, db: DbSession) -> AutofillPlan:
    """What to put in each field the extension found. Standard fields are matched by
    rule; the rest go to the model when one is configured. Sensitive questions always
    come back in `needs_user`."""
    with ai_errors():
        result = autofill.plan(db, user.id, payload)
    db.commit()
    return result
