"""Migrations are reversible and match the ORM models (no autogenerate drift)."""

import asyncio
import os

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401
from app.core.db import Base
from tests.conftest import run_alembic


def _diff() -> list[object]:
    async def run() -> list[object]:
        engine = create_async_engine(os.environ["DATABASE_URL"])
        async with engine.connect() as conn:
            diff = await conn.run_sync(
                lambda sync: compare_metadata(
                    MigrationContext.configure(sync, opts={"compare_type": True}), Base.metadata
                )
            )
        await engine.dispose()
        return list(diff)

    return asyncio.run(run())


def test_models_match_migrations() -> None:
    assert _diff() == []


def test_downgrade_and_upgrade_roundtrip() -> None:
    run_alembic("downgrade", "base")
    run_alembic("upgrade", "head")
    assert _diff() == []
