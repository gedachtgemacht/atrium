import asyncio
import logging
from collections.abc import Coroutine

log = logging.getLogger("atrium.tasks")


class TaskRunner:
    """Background work inside the app process (agent runs, memory extraction, summaries)."""

    def __init__(self):
        self._tasks: set[asyncio.Task] = set()
        self._debounce: dict[str, asyncio.Task] = {}

    def spawn(self, coro: Coroutine, name: str = "") -> asyncio.Task:
        task = asyncio.create_task(self._guard(coro, name), name=name or None)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def debounce(self, key: str, delay: float, factory) -> None:
        old = self._debounce.get(key)
        if old and not old.done():
            old.cancel()

        async def later():
            await asyncio.sleep(delay)
            await factory()

        self._debounce[key] = self.spawn(later(), name=f"debounce:{key}")

    async def _guard(self, coro: Coroutine, name: str):
        try:
            return await coro
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("background task %s failed", name)

    async def drain(self, timeout: float = 30) -> None:
        """Wait until no background task is left (tests)."""
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while self._tasks:
            pending = [t for t in self._tasks if not t.done()]
            if not pending:
                break
            await asyncio.wait(pending, timeout=max(0.01, end - loop.time()))
            if loop.time() > end:
                raise TimeoutError("background tasks did not finish")

    async def shutdown(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
