import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.modules.ai.repository import AIGenerationRepository
from app.modules.ai.router import project_router as ai_project_router
from app.modules.ai.router import router as ai_router
from app.modules.auth.router import router as auth_router
from app.modules.demo.router import router as demo_router
from app.modules.editing.router import router as editing_router
from app.modules.generation.router import design_router
from app.modules.generation.router import router as generation_router
from app.modules.health.router import router as health_router
from app.modules.jobs.repository import JobRepository
from app.modules.jobs.router import router as jobs_router
from app.modules.projects.router import router as projects_router
from app.modules.versions.router import router as versions_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Jobs run in-process: any left queued/running belong to a previous process.
    try:
        async with get_sessionmaker()() as session:
            count = await JobRepository(session).fail_interrupted()
            count += await AIGenerationRepository(session).fail_interrupted()
            await session.commit()
        if count:
            logger.warning("Marked %d interrupted job(s)/generation(s) as failed", count)
    except Exception:
        logger.warning("Could not check for interrupted jobs", exc_info=True)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="BuildAI 3D API",
        version="0.3.0",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    register_error_handlers(app)

    app.include_router(health_router)
    v1 = APIRouter(prefix="/api/v1")
    v1.include_router(auth_router)
    v1.include_router(projects_router)
    v1.include_router(versions_router)
    v1.include_router(editing_router)
    v1.include_router(generation_router)
    v1.include_router(design_router)
    v1.include_router(jobs_router)
    v1.include_router(ai_router)
    v1.include_router(ai_project_router)
    v1.include_router(demo_router)
    app.include_router(v1)
    return app


app = create_app()
