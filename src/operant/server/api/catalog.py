"""
Capability and profile routes: browse, approve, invoke, edit.

Import as:

import operant.server.api.catalog as catalog
"""

from __future__ import annotations

from typing import Annotated, Any, Dict

import fastapi

import operant.domain.governance as govern
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
    gate = govern.StabilityGate(
        min_runs=state.settings.governance.min_runs,
        min_success_rate=state.settings.governance.min_success_rate,
    )
    return gate


def _summary(
    capability: artifact.CapabilityArtifact,
    state: deps.ServerState,
) -> Dict[str, Any]:
    """
    Render a capability with its stability and gate status.
    """
    stability = state.runs.stability(capability.id)
    gate = _gate(state)
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
def approve_capability(capability_id: str, state: State) -> Any:
    """
    Approve a capability once its stability clears the gate.
    """
    stability = state.runs.stability(capability_id)
    if not _gate(state).passes(stability.runs, stability.successes):
        raise fastapi.HTTPException(
            status_code=409, detail="stability gate not met"
        )
    capability = state.artifacts.approve(capability_id)
    summary = _summary(capability, state)
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
    Validate and stores an edited app profile.
    """
    if document.vendor_id != profile_id:
        raise fastapi.HTTPException(
            status_code=422, detail="vendor_id must match the path"
        )
    state.profiles.save(document)
    dumped = document.model_dump()
    return dumped
