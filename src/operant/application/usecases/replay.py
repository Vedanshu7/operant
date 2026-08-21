"""
Replay a saved capability deterministically (no LLM).

Import as:

import operant.application.usecases.replay as replay
"""

from __future__ import annotations

import collections.abc
import dataclasses
from typing import Dict, Optional

import operant.application.context as accontex
import operant.application.replay.options as rooption
import operant.application.replay.traverse as traverse
import operant.domain.models.results as results
import operant.infra.repositories.artifacts as artifact
import operant.infra.repositories.graphs as rggraphs
import operant.infra.repositories.profiles as rpprofil
import operant.ports.hitl as hitl

# #############################################################################
# ReplayRequest
# #############################################################################


@dataclasses.dataclass(frozen=True)
class ReplayRequest:
    """
    One replay invocation.

    :ivar capability_id: Capability to replay.
    :ivar tenant: Tenant override; the capability's default when empty.
    :ivar inputs: Task inputs by name.
    :ivar inject_session_expiry_before: Edge id to fault before, for
        demos.
    """

    capability_id: str
    tenant: str = ""
    inputs: Optional[Dict[str, str]] = None
    inject_session_expiry_before: Optional[str] = None


def execute_replay(
    request: ReplayRequest,
    *,
    factory: accontex.ContextBuilder,
    artifacts: artifact.FileArtifactRepository,
    graphs: rggraphs.FileGraphRepository,
    profiles: rpprofil.FileProfileRepository,
    approver: Optional[hitl.Approver] = None,
    run_identifier: Optional[str] = None,
    on_context: Optional[
        collections.abc.Callable[[accontex.RunContext], None]
    ] = None,
) -> results.ReplayResult:
    """
    Load a capability, wires a run, and replays it.

    :param request: What to replay.
    :param factory: Builds the run context (surface, log, broker).
    :param artifacts: Where capabilities are stored.
    :param graphs: Where graph versions are stored.
    :param profiles: Where app profiles are stored.
    :param approver: Answers approvals; deny-by-default when ``None``.
    :param run_identifier: Fixes the run id and evidence directory; the
        server passes the id it tracks the run under.
    :param on_context: Called with the wired context before the run
        starts, so a caller can attach evidence and broker listeners.
    :return: The typed replay result.
    """
    capability = artifacts.get(request.capability_id)
    graph = graphs.get(capability.vendor_id, capability.graph_version)
    profile = profiles.get(capability.policy_scope.policy_id)
    context = factory.build(
        "replay", profile, approver=approver, run_identifier=run_identifier
    )
    if on_context is not None:
        on_context(context)
    try:
        options = rooption.ReplayOptions(
            tenant=request.tenant or capability.default_tenant,
            params=dict(request.inputs or {}),
            inject_session_expiry_before=request.inject_session_expiry_before,
        )
        result = traverse.run_capability(
            capability,
            graph,
            context.surface,
            context.broker,
            context.log,
            context.redactor,
            options,
            graph_store=graphs,
            approver=context.approver,
        )
    finally:
        context.close()
    return result


def is_success(result: results.ReplayResult) -> bool:
    """
    Whether a result counts as a successful replay for stability.
    """
    ok = result.status in {"success", "business_outcome"}
    return ok
