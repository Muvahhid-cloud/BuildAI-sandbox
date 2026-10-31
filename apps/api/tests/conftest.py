"""Test configuration.

Database: uses TEST_DATABASE_URL when set (CI, Docker). Otherwise starts an embedded
PostgreSQL via `pgserver` (dev dependency) so tests run against real Postgres locally
without Docker. The schema is created with Alembic migrations, not metadata.create_all,
so migrations are exercised by every test run.
"""

import asyncio
import importlib
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
_pg_server: Any = None


def _embedded_database_url() -> str:
    global _pg_server
    pgserver: Any = importlib.import_module("pgserver")  # dev-only dependency

    data_dir = API_ROOT / ".pytest_cache" / "pgdata"
    data_dir.mkdir(parents=True, exist_ok=True)
    _pg_server = pgserver.get_server(data_dir, cleanup_mode="stop")
    admin_uri: str = _pg_server.get_uri()

    # pgserver.psql() shells out unquoted and breaks on paths with spaces; use asyncpg.
    async def recreate() -> None:
        import asyncpg

        conn = await asyncpg.connect(admin_uri)
        try:
            await conn.execute("DROP DATABASE IF EXISTS buildai_test WITH (FORCE)")
            await conn.execute("CREATE DATABASE buildai_test")
        finally:
            await conn.close()

    asyncio.run(recreate())
    uri: str = _pg_server.get_uri(database="buildai_test")
    return uri.replace("postgresql://", "postgresql+asyncpg://", 1)


def run_alembic(*args: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    getattr(command, args[0])(cfg, *args[1:])


def pytest_configure(config: pytest.Config) -> None:
    url = os.environ.get("TEST_DATABASE_URL") or _embedded_database_url()
    os.environ["DATABASE_URL"] = url
    os.environ["ENVIRONMENT"] = "test"
    os.environ["JWT_SECRET"] = "test-secret-" + "x" * 32
    os.environ["COOKIE_SECURE"] = "false"
    os.environ["CORS_ORIGINS"] = ""
    # Tests never call a paid API (CLAUDE.md rule 13); live tests opt in explicitly.
    os.environ["AI_PROVIDER"] = "mock"
    run_alembic("downgrade", "base")
    run_alembic("upgrade", "head")


def pytest_unconfigure(config: pytest.Config) -> None:
    if _pg_server is not None:
        _pg_server.cleanup()


@pytest.fixture(autouse=True)
async def _clean_tables() -> AsyncIterator[None]:
    yield
    from sqlalchemy import text

    from app.core.db import get_engine

    async with get_engine().begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE users, refresh_tokens, projects, project_versions, jobs, "
                "ai_generations, ai_runs CASCADE"
            )
        )


@pytest.fixture
async def client() -> AsyncIterator[Any]:
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def register(
    client: Any, email: str = "ada@example.com", password: str = "correct-horse-battery"
) -> dict[str, Any]:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": "Ada"},
    )
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()
    return data


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
