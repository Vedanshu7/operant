"""
System routes: health and a run's evidence files.

Import as:

import operant.server.api.system as system
"""

from __future__ import annotations

from typing import Annotated, Any

import fastapi
import fastapi.responses as response

import operant
import operant.server.deps as deps

router = fastapi.APIRouter(tags=["system"])

State = Annotated[deps.ServerState, fastapi.Depends(deps.get_state)]

_KINDS = {".png": "png", ".jsonl": "jsonl", ".log": "log"}


@router.get("/health")
def health() -> Any:
    """
    Report liveness and the package version.
    """
    status = {"ok": True, "version": operant.__version__}
    return status


@router.get("/evidence/{run_id}")
def list_evidence(run_id: str, state: State) -> Any:
    """
    List the evidence files a run produced.
    """
    run = state.runs.get(run_id)
    directory = state.settings.paths.evidence_dir / (run.evidence_dir or run_id)
    files = [
        {
            "path": path.name,
            "size": path.stat().st_size,
            "kind": _KINDS.get(path.suffix, "other"),
        }
        for path in sorted(directory.glob("*"))
        if path.is_file()
    ]
    listing = {"files": files}
    return listing


@router.get("/evidence/{run_id}/files/{name}")
def get_evidence_file(run_id: str, name: str, state: State) -> response.Response:
    """
    Serve one evidence file, guarding against path traversal.
    """
    run = state.runs.get(run_id)
    directory = (
        state.settings.paths.evidence_dir / (run.evidence_dir or run_id)
    ).resolve()
    target = (directory / name).resolve()
    if directory != target.parent or not target.is_file():
        raise fastapi.HTTPException(status_code=404, detail="no such file")
    file = response.FileResponse(target)
    return file
