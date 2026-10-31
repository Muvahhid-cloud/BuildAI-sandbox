"""Start (or reuse) an embedded PostgreSQL for local development without Docker.

Usage (from repo root):  pnpm db:local
Prints the DATABASE_URL to put in your .env. The server keeps running in the background;
data lives in apps/api/.localdb (gitignored). Stop it with:  pnpm db:local --stop
"""

import asyncio
import importlib
import sys
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[1] / ".localdb"
DB_NAME = "buildai"


async def _ensure_database(admin_uri: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(admin_uri)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", DB_NAME)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{DB_NAME}"')
    finally:
        await conn.close()


def main() -> None:
    pgserver: Any = importlib.import_module("pgserver")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    server = pgserver.get_server(DATA_DIR, cleanup_mode=None)
    if "--stop" in sys.argv:
        server.cleanup_mode = "stop"
        server.cleanup()
        print("Embedded PostgreSQL stopped.")
        return
    asyncio.run(_ensure_database(server.get_uri()))
    uri: str = server.get_uri(database=DB_NAME)
    print("Embedded PostgreSQL is running. Add this to your .env:\n")
    print("DATABASE_URL=" + uri.replace("postgresql://", "postgresql+asyncpg://", 1))


if __name__ == "__main__":
    main()
