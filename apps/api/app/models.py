"""Import every ORM model so Base.metadata is complete (used by Alembic and tests)."""

from app.modules.ai.models import AIGeneration, AIRun
from app.modules.auth.models import RefreshToken, User
from app.modules.jobs.models import Job
from app.modules.projects.models import Project
from app.modules.versions.models import ProjectVersion

__all__ = ["AIGeneration", "AIRun", "Job", "Project", "ProjectVersion", "RefreshToken", "User"]
