"""
Capability and profile routes: browse, approve, invoke, edit.

Import as:

import operant.server.api.catalog as catalog
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

import fastapi

import operant.application.capabilities as apcapab
import operant.domain.errors as errors
import operant.domain.governance as govern
import operant.domain.graph.review as review
import operant.domain.models.artifact as artifact
import operant.domain.profile as profile
import operant.server.deps as deps
import operant.server.schemas as schemas

router = fastapi.APIRouter(tags=["catalog"])

State = Annotated[deps.ServerState, fastapi.Depends(deps.get_state)]


def _gate(state: deps.ServerState) -> govern.StabilityGate:
    """
    Build the stability gate from the configured governance thresholds.
    """
    gate = state.settings.governance.gate()
    return gate


def _summary(
    capability: artifact.CapabilityArtifact,
    state: deps.ServerState,
) -> Dict[str, Any]:
    """
    Render a capability with its stability and gate status.
    """
    gate = _gate(state)
    stability = state.runs.stability(capability.id, window=gate.window)
    summary = {
        "id": capability.id,
        "name": capability.name,
        "description": capability.description,
        "vendor_id": capability.vendor_id,
        "version": capability.version,
        "graph_version": capability.graph_version,
        "status": capability.status,
        "stability": stability.model_dump(),
        "gate": {
            "min_runs": gate.min_runs,
            "min_success_rate": gate.min_success_rate,
            "passes": gate.passes(stability.runs, stability.successes),
        },
    }
    return summary


@router.get("/capabilities")
def list_capabilities(state: State) -> Any:
    """
    List every stored capability with its stability and gate.
    """
    items = [_summary(cap, state) for cap in state.artifacts.list()]
    return items


@router.get("/capabilities/{capability_id}")
def get_capability(capability_id: str, state: State) -> Any:
    """
    Return one capability's full contract, stability, and gate.
    """
    capability = state.artifacts.get(capability_id)
    detail = capability.model_dump()
    detail.update(_summary(capability, state))
    pinned = state.graphs.get(capability.vendor_id, capability.graph_version)
    outstanding = {
        edge.id
        for edge in apcapab.outstanding_steps(
            capability, state.graphs, state.runs.edge_records
        )
    }
    detail["unknown_steps"] = [
        {
            "edge": edge.id,
            "description": edge.description,
            "judged": edge.judged,
            "reviewed": edge.id not in outstanding,
        }
        for edge in review.unknown_steps(pinned, capability.compiled_path)
    ]
    detail["latest_graph_version"] = state.graphs.head(capability.vendor_id)
    return detail


@router.get("/capabilities/{capability_id}/graph")
def get_capability_graph(capability_id: str, state: State) -> Any:
    """
    Return the graph version the capability pins.
    """
    capability = state.artifacts.get(capability_id)
    graph = state.graphs.get(capability.vendor_id, capability.graph_version)
    dumped = graph.model_dump()
    return dumped


@router.post("/capabilities/{capability_id}/approve")
def approve_capability(
    capability_id: str,
    state: State,
    body: Optional[schemas.ApproveCapabilityBody] = None,
) -> Any:
    """
    Approve a capability a person has reviewed, once it clears the gate.
    """
    request = body or schemas.ApproveCapabilityBody()
    gate = _gate(state)
    stability = state.runs.stability(capability_id, window=gate.window)
    if not request.force and not gate.passes(stability.runs, stability.successes):
        raise fastapi.HTTPException(
            status_code=409, detail="stability gate not met"
        )
    current = state.artifacts.get(capability_id)
    outstanding = apcapab.outstanding_steps(
        current, state.graphs, state.runs.edge_records
    )
    unseen = [e.id for e in outstanding if e.id not in request.reviewed_edges]
    if outstanding and (request.graph_version != current.graph_version or unseen):
        raise fastapi.HTTPException(
            status_code=409,
            detail="review these steps first: "
            + ", ".join(e.description for e in outstanding),
        )
    capability = state.artifacts.approve(capability_id)
    apcapab.review_unknown_steps(
        capability, state.graphs, state.runs.edge_records, by="api approve"
    )
    summary = _summary(capability, state)
    return summary


@router.post("/capabilities/{capability_id}/repin")
def repin_capability(capability_id: str, state: State) -> Any:
    """
    Move a capability to the newest graph version, as a draft.
    """
    try:
        moved = apcapab.repin(
            state.artifacts.get(capability_id),
            graph_store=state.graphs,
            artifact_store=state.artifacts,
            run_repo=state.runs,
            by="api repin",
        )
    except errors.RepinRefusedError as err:
        raise fastapi.HTTPException(status_code=409, detail=str(err)) from err
    summary = _summary(moved, state)
    return summary


@router.post("/capabilities/{capability_id}/invoke")
def invoke_capability(
    capability_id: str, body: schemas.StartReplayBody, state: State
) -> Any:
    """
    Replay a capability with the supplied tenant and inputs.
    """
    request = body.model_copy(update={"capability_id": capability_id})
    run = state.manager.start_replay(request.to_request())
    summary = schemas.run_summary(run)
    return summary


@router.get("/profiles")
def list_profiles(state: State) -> Any:
    """
    List stored app profiles.
    """
    items = [
        {
            "id": document.vendor_id,
            "vendor_id": document.vendor_id,
            "app_name": document.app_name,
            "tenants": sorted(document.tenants),
        }
        for document in state.profiles.list()
    ]
    return items


@router.get("/profiles/{profile_id}")
def get_profile(profile_id: str, state: State) -> Any:
    """
    Return one app profile's full document.
    """
    document = state.profiles.get(profile_id).model_dump()
    return document


@router.put("/profiles/{profile_id}")
def save_profile(
    profile_id: str, document: profile.AppProfile, state: State
) -> Any:
    """
    Validate and store an edited app profile.
    """
    if document.vendor_id != profile_id:
        raise fastapi.HTTPException(
            status_code=422, detail="vendor_id must match the path"
        )
    state.profiles.save(document)
    dumped = document.model_dump()
    return dumped


@router.put("/profiles/{profile_id}/tenants/{tenant}")
def save_tenant(
    profile_id: str,
    tenant: str,
    binding: artifact.TenantBinding,
    state: State,
) -> Any:
    """
    Add or replace one tenant binding and return the updated profile.
    """
    current = state.profiles.get(profile_id)
    updated = current.model_copy(
        update={"tenants": {**current.tenants, tenant: binding}}
    )
    state.profiles.save(updated)
    dumped = updated.model_dump()
    return dumped
