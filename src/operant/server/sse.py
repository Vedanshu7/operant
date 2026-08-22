"""
Server-sent-event streaming of a run's events to the operator UI.

The stream subscribes to the live hub first, then replays the run's
indexed events after the client's cursor, dropping any live event
already covered by the replay. It ends when a terminal run status is
emitted.

Import as:

import operant.server.sse as sse
"""

from __future__ import annotations

import collections.abc
import dataclasses
import json
from typing import Any, Dict

import sse_starlette.sse

import operant.domain.models.runs as runs
import operant.server.deps as deps
import operant.server.jobs.hub as hub


def _encode(envelope: hub.SseEnvelope) -> Dict[str, Any]:
    """
    Render an envelope as the SSE field mapping the client reads.
    """
    encoded = {
        "event": envelope.type,
        "id": str(envelope.seq),
        "data": json.dumps(dataclasses.asdict(envelope)),
    }
    return encoded


def _is_terminal(envelope: hub.SseEnvelope) -> bool:
    """
    Whether the envelope carries a terminal run status.
    """
    terminal = envelope.run_status in runs.TERMINAL_STATUSES
    return terminal


def run_event_stream(
    state: deps.ServerState, run_id: str, after_seq: int
) -> sse_starlette.sse.EventSourceResponse:
    """
    Build an SSE response streaming ``run_id``'s events after a cursor.
    """

    async def generator() -> collections.abc.AsyncIterator[Dict[str, Any]]:
        queue, subscription = await state.hub.subscribe(run_id)
        try:
            seen = after_seq
            for envelope in state.manager.replay_stream(run_id, after_seq):
                seen = max(seen, envelope.seq)
                yield _encode(envelope)
            if state.manager.is_terminal(run_id):
                return
            while True:
                envelope = await queue.get()
                if envelope.seq <= seen:
                    continue
                seen = envelope.seq
                yield _encode(envelope)
                if _is_terminal(envelope):
                    return
        finally:
            await subscription.close()

    stream = sse_starlette.sse.EventSourceResponse(generator())
    return stream
