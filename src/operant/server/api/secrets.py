"""
Secret-reference routes: declare references and check presence.

Only reference metadata is stored or returned; a secret's value never
crosses this boundary. Presence is a boolean the configured store
reports.

Import as:

import operant.server.api.secrets as secrets
"""

from __future__ import annotations

import dataclasses
from typing import Annotated, Any, Dict

import fastapi

import operant.server.deps as deps
import operant.server.schemas as schemas

router = fastapi.APIRouter(tags=["secrets"])

State = Annotated[deps.ServerState, fastapi.Depends(deps.get_state)]


def _view(record: Any, present: bool) -> Dict[str, Any]:
    """
    Render a secret reference with its resolved presence flag.
    """
    data = dataclasses.asdict(record)
    data["present"] = present
    return data


@router.get("/secrets/refs")
def list_refs(state: State) -> Any:
    """
    List declared secret references with their current presence.
    """
    items = [
        _view(record, state.secret_store.exists(record.locator))
        for record in state.secret_refs.list()
    ]
    return items


@router.post("/secrets/refs")
def upsert_ref(body: schemas.SecretRefBody, state: State) -> Any:
    """
    Declare or replaces a secret reference (metadata only).
    """
    meta = body.to_meta()
    state.secret_refs.upsert(meta)
    present = state.secret_store.exists(meta.locator)
    state.secret_refs.mark_presence(meta.name, present)
    view = _view(meta, present)
    return view


@router.delete("/secrets/refs/{name}")
def delete_ref(name: str, state: State) -> Any:
    """
    Remove a secret reference declaration.
    """
    state.secret_refs.delete(name)
    result = {"ok": True}
    return result


@router.get("/secrets/refs/{name}/check")
def check_ref(name: str, state: State) -> Any:
    """
    Report whether the store currently resolves the reference.
    """
    result = None
    for record in state.secret_refs.list():
        if record.name == name:
            present = state.secret_store.exists(record.locator)
            state.secret_refs.mark_presence(name, present)
            result = {"name": name, "present": present}
            break
    if result is None:
        raise fastapi.HTTPException(status_code=404, detail="no such reference")
    return result
