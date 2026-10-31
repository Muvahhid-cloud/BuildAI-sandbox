"""In-process background job runner (ADR-010: in-process first, a worker later).

`submit()` schedules a coroutine on the running event loop and keeps a strong reference until
it finishes. The interface is deliberately tiny so a real queue (arq + Redis) can replace it
without changing callers. Jobs do not survive a process restart: on startup, jobs left queued or
running are marked failed (see `fail_interrupted_jobs`).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class JobRunner:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    def submit(self, name: str, work: Callable[[], Awaitable[None]]) -> None:
        async def run() -> None:
            try:
                await work()
            except Exception:  # the job itself records failures; this is a last resort
                logger.exception("Background job %s crashed", name)

        task = asyncio.get_running_loop().create_task(run(), name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Wait for all submitted jobs (tests, graceful shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)


job_runner = JobRunner()
