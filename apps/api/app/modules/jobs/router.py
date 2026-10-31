import uuid

from fastapi import APIRouter

from app.core.errors import NotFoundError
from app.modules.auth.dependencies import CurrentUser, SessionDep
from app.modules.jobs.repository import JobRepository
from app.modules.jobs.schemas import JobOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}")
async def get_job(job_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> JobOut:
    job = await JobRepository(session).get(job_id)
    if job is None or job.user_id != user.id:  # 404, not 403: ids can't be probed
        raise NotFoundError("Job not found")
    return JobOut.model_validate(job)
