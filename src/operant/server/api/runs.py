"""
Run lifecycle routes: start, list, inspect, stream, cancel.

Import as:

import operant.server.api.runs as arruns
"""

from __future__ import annotations

import pathlib
from typing import Annotated, Any, Optional

import fastapi
import fastapi.responses as response

import operant.domain.models.runs as runs
import operant.server.api.pending as pending
import operant.server.deps as deps
import operant.server.schemas as schemas
import operant.server.sse as sse

router = fastapi.APIRouter(tags=["runs"])

State = Annotated[deps.ServerState, fastapi.Depends(deps.get_state)]


@router.post("/runs/discovery")
def start_discovery(body: schemas.StartDiscoveryBody, state: State) -> Any:
    """
    Start an LLM discovery run and returns its initial record.
    """
    run = state.manager.start_discovery(body.to_request())
    summary = schemas.run_summary(run)
    return summary


@router.post("/runs/replay")
def start_replay(body: schemas.StartReplayBody, state: State) -> Any:
    """
    Start a deterministic replay run and returns its initial record.
    """
    run = state.manager.start_replay(body.to_request())
    summary = schemas.run_summary(run)
    return summary


@router.get("/runs")
def list_runs(
    state: State,
    kind: Optional[runs.RunKind] = None,
    status: Optional[runs.RunStatus] = None,
    capability_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Any:
    """
    List runs newest first, filtered by the given criteria.
    """
    criteria = runs.RunFilter(
        status=status,
        kind=kind,
        capability_id=capability_id,
        limit=limit,
        offset=offset,
    )
    items = [schemas.run_summary(run) for run in state.runs.list(criteria)]
    page = {"items": items, "next_cursor": None}
    return page


@router.get("/runs/{run_id}")
def get_run(run_id: str, state: State) -> Any:
    """
    Return a run with its pending human-in-the-loop state.
    """
    run = state.runs.get(run_id)
    position = state.lease.position(run_id)
    detail = schemas.run_detail(
        run,
        pending_approval=pending.pending_approval(state.runs, run_id),
        pending_intervention=pending.pending_intervention(state.runs, run_id),
        pending_clarification=pending.pending_clarification(state.runs, run_id),
        lease_position=position if position > 0 else None,
    )
    return detail


@router.get("/runs/{run_id}/events")
def stream_events(
    run_id: str, state: State, after: int = -1
) -> response.Response:
    """
    Stream the run's events over SSE, replaying after ``after``.
    """
    state.runs.get(run_id)
    stream = sse.run_event_stream(state, run_id, after)
    return stream


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, state: State) -> Any:
    """
    Request cancellation of an in-flight run.
    """
    state.runs.get(run_id)
    state.manager.cancel(run_id)
    result = {"ok": True}
    return result


@router.get("/runs/{run_id}/screenshot")
def latest_screenshot(run_id: str, state: State) -> response.Response:
    """
    Return the most recent screenshot captured for the run.
    """
    run = state.runs.get(run_id)
    directory = state.settings.paths.evidence_dir / (run.evidence_dir or run_id)
    shots = sorted(directory.glob("*.png"))
    if not shots:
        raise fastapi.HTTPException(status_code=404, detail="no screenshot yet")
    file = response.FileResponse(_safe(directory, shots[-1]))
    return file


def _safe(directory: pathlib.Path, candidate: pathlib.Path) -> pathlib.Path:
    """
    Resolve a candidate path, rejecting one outside ``directory``.
    """
    resolved = candidate.resolve()
    if directory.resolve() not in resolved.parents:
        raise fastapi.HTTPException(status_code=404, detail="not found")
    return resolved
