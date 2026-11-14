import uuid

from fastapi import APIRouter

from app.core.errors import NotFoundError
from app.modules.auth.dependencies import CurrentUser, SessionDep
from app.modules.jobs.repository import JobRepository
from app.modules.jobs.schemas import JobOut, PreviewModelOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}")
async def get_job(job_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> JobOut:
    job = await JobRepository(session).get(job_id)
    if job is None or job.user_id != user.id:  # 404, not 403: ids can't be probed
        raise NotFoundError("Job not found")
    return JobOut.model_validate(job)


@router.get("/{job_id}/preview")
async def get_job_preview(
    job_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> PreviewModelOut:
    """The laid-out building of a running generation job, available as soon as the layout stage
    is done (`preview_model_hash` on the job) while the rules check and saving continue. It is
    exactly the model the new version stores. 404 before the layout and once the job ended."""
    repo = JobRepository(session)
    job = await repo.get(job_id)
    if job is None or job.user_id != user.id:
        raise NotFoundError("Job not found")
    preview = await repo.preview(job_id)
    if preview is None:
        raise NotFoundError("No preview model for this job")
    return PreviewModelOut(model=preview[0], model_hash=preview[1])
