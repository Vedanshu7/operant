"""
Per-run server-sent-event fan-out from worker threads to subscribers.

Worker threads publish envelopes with ``publish`` (thread-safe via the
event loop); HTTP handlers ``subscribe`` and receive them as an async
stream. A subscriber first replays the run's indexed events after its
cursor, then follows the live queue, so a reconnect misses nothing.

Import as:

import operant.server.jobs.hub as jhhub
"""

from __future__ import annotations

import asyncio
import collections.abc
import contextlib
import dataclasses
from typing import Any, Dict, List, Optional, Tuple

# #############################################################################
# SseEnvelope
# #############################################################################


@dataclasses.dataclass
class SseEnvelope:
    """
    One server-sent event.

    :ivar run_id: Run the event belongs to.
    :ivar seq: Monotonic sequence within the run (``-1`` for server-only
        events that are not indexed).
    :ivar at: ISO timestamp.
    :ivar type: Event type name.
    :ivar summary: One-line human summary.
    :ivar data: Structured payload.
    :ivar run_status: The run's status at emit time.
    :ivar screenshot: Screenshot file name, when the event carries one.
    """

    run_id: str
    type: str
    at: str = ""
    seq: int = -1
    summary: str = ""
    data: Dict[str, Any] = dataclasses.field(default_factory=dict)
    run_status: str = ""
    screenshot: Optional[str] = None


# #############################################################################
# EventHub
# #############################################################################


class EventHub:
    """
    Fan run events out to SSE subscribers, across the thread boundary.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._queues: Dict[str, List[asyncio.Queue[SseEnvelope]]] = {}
        self._lock = asyncio.Lock()

    def publish(self, envelope: SseEnvelope) -> None:
        """
        Deliver an envelope to a run's subscribers (thread-safe).

        A closed loop (the server is shutting down) is ignored: no
        subscriber remains, and the evidence log and database index
        already hold the event.
        """
        with contextlib.suppress(RuntimeError):
            self._loop.call_soon_threadsafe(self._fan_out, envelope)

    async def subscribe(
        self, run_id: str
    ) -> Tuple[asyncio.Queue[SseEnvelope], Subscription]:
        """
        Register a live queue for ``run_id``.

        :return: The queue and a subscription handle that unregisters
            it.
        """
        queue: asyncio.Queue[SseEnvelope] = asyncio.Queue()
        async with self._lock:
            self._queues.setdefault(run_id, []).append(queue)
        subscription = Subscription(self, run_id, queue)
        return queue, subscription

    async def stream(
        self, run_id: str, replay: List[SseEnvelope]
    ) -> collections.abc.AsyncIterator[SseEnvelope]:
        """
        Yield replayed events, then live ones until the run is terminal.
        """
        queue, subscription = await self.subscribe(run_id)
        try:
            for envelope in replay:
                yield envelope
            while True:
                yield await queue.get()
        finally:
            await subscription.close()

    def _fan_out(self, envelope: SseEnvelope) -> None:
        """
        Push an envelope onto every subscriber queue for its run.
        """
        for queue in self._queues.get(envelope.run_id, []):
            queue.put_nowait(envelope)

    async def _remove(
        self, run_id: str, queue: asyncio.Queue[SseEnvelope]
    ) -> None:
        """
        Drop a subscriber queue, forgetting the run when it has none.
        """

        async with self._lock:
            queues = self._queues.get(run_id, [])
            if queue in queues:
                queues.remove(queue)
            if not queues:
                self._queues.pop(run_id, None)


# #############################################################################
# Subscription
# #############################################################################


@dataclasses.dataclass
class Subscription:
    """
    A live SSE subscription; closing it unregisters the queue.
    """

    hub: EventHub
    run_id: str
    queue: asyncio.Queue[SseEnvelope]

    async def close(self) -> None:
        """
        Unregister this subscription's queue from the hub.
        """
        await self.hub._remove(self.run_id, self.queue)
