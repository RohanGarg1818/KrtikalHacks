"""In-memory pub/sub of per-run events for SSE streams.

Single-process only: one FastAPI process runs the API, runner, scheduler, and
Telegram bot, so a module-level bus is sufficient. Each run keeps a bounded
history so clients that subscribe slightly late still receive every event.
"""

from __future__ import annotations

import asyncio
import contextlib
import time

HISTORY_LIMIT = 1000
FINISHED_RETENTION_SECONDS = 600


class RunEventBus:
    def __init__(self) -> None:
        self._queues: dict[str, set[asyncio.Queue[dict | None]]] = {}
        self._history: dict[str, list[dict]] = {}
        self._finished_at: dict[str, float] = {}

    def subscribe(
        self, run_id: str
    ) -> tuple[list[dict], asyncio.Queue[dict | None]]:
        self._prune()
        past = list(self._history.get(run_id, ()))
        queue: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=5000)
        self._queues.setdefault(run_id, set()).add(queue)
        return past, queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[dict | None]) -> None:
        subscribers = self._queues.get(run_id)
        if subscribers is None:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._queues.pop(run_id, None)

    def publish(self, run_id: str, event: dict) -> None:
        history = self._history.setdefault(run_id, [])
        history.append(event)
        if len(history) > HISTORY_LIMIT:
            del history[: len(history) - HISTORY_LIMIT]
        for queue in list(self._queues.get(run_id, ())):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)

    def finish(self, run_id: str) -> None:
        """Wake subscribers so they can stop waiting after the final event."""
        self._finished_at[run_id] = time.monotonic()
        for queue in list(self._queues.get(run_id, ())):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(None)

    def _prune(self) -> None:
        now = time.monotonic()
        expired = [
            run_id
            for run_id, stamp in self._finished_at.items()
            if now - stamp > FINISHED_RETENTION_SECONDS
        ]
        for run_id in expired:
            self._finished_at.pop(run_id, None)
            self._history.pop(run_id, None)
            self._queues.pop(run_id, None)


run_events = RunEventBus()
