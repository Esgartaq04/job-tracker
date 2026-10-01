import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CoverLetterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    content: str
    created_at: datetime
    updated_at: datetime | None = None


class CoverLetterUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
