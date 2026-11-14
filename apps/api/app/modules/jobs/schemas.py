import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

JobStatus = Literal["queued", "running", "succeeded", "failed"]


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    kind: str
    status: JobStatus
    stage: str | None
    progress: float
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    # Set while the laid-out model can be read from GET /jobs/{id}/preview (before it is saved).
    preview_model_hash: str | None = None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class PreviewModelOut(BaseModel):
    """The laid-out building of a running generation (spec-form job or AI generation), before
    it is saved: exactly the JSON (and hash) the new version will store."""

    model: dict[str, Any]
    model_hash: str
