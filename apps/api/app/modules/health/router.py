from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import get_engine
from app.core.disclaimer import DISCLAIMER

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "buildai-api", "disclaimer": DISCLAIMER}


@router.get("/health/db", response_model=None)
async def health_db() -> dict[str, str] | JSONResponse:
    try:
        async with get_engine().connect() as conn:
            version = await conn.scalar(text("show server_version"))
    except (SQLAlchemyError, OSError) as exc:
        return JSONResponse(
            {"error": {"code": "DB_UNAVAILABLE", "message": type(exc).__name__, "details": []}},
            status_code=503,
        )
    return {"status": "ok", "postgres": str(version)}
