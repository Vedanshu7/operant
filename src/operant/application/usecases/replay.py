"""
Replay a saved capability deterministically (no LLM).

Import as:

import operant.application.usecases.replay as replay
"""

from __future__ import annotations

import collections.abc
import dataclasses
from typing import Dict, Final, Optional

import operant.application.context as accontex
import operant.application.replay.options as rooption
import operant.application.replay.traverse as traverse
import operant.domain.models.results as results
import operant.ports.hitl as hitl
import operant.ports.repositories as prepos

# #############################################################################
# ReplayRequest
# #############################################################################


@dataclasses.dataclass(frozen=True)
class ReplayRequest:
    """
    One replay invocation.

    :ivar capability_id: capability to replay.
    :ivar tenant: tenant override; the capability's default when empty.
    :ivar inputs: task inputs by name.
    :ivar inject_session_expiry_before: edge id to fault before, for
        demos.
    """

    capability_id: str
    tenant: str = ""
    inputs: Optional[Dict[str, str]] = None
    inject_session_expiry_before: Optional[str] = None


_NOT_BREAKAGE: Final = frozenset(
    {"cancelled", "approval_denied", "unreviewed_step"}
)


def execute_replay(
    request: ReplayRequest,
    *,
    factory: accontex.ContextBuilder,
    artifacts: prepos.ArtifactRepository,
    graphs: prepos.GraphRepository,
    profiles: prepos.ProfileRepository,
    approver: Optional[hitl.Approver] = None,
    run_identifier: Optional[str] = None,
    edge_records: Optional[prepos.EdgeRecordRepository] = None,
    should_stop: Optional[collections.abc.Callable[[], bool]] = None,
    on_context: Optional[
        collections.abc.Callable[[accontex.RunContext], None]
    ] = None,
) -> results.ReplayResult:
    """
    Load a capability, wires a run, and replays it.

    :param request: what to replay.
    :param factory: builds the run context (surface, log, broker).
    :param artifacts: where capabilities are stored.
    :param graphs: where graph versions are stored.
    :param profiles: where app profiles are stored.
    :param approver: answers approvals; deny-by-default when ``None``.
    :param run_identifier: fixes the run id and evidence directory; the
        server passes the id it tracks the run under.
    :param edge_records: people's reviews of unknown steps; ``None``
        counts every unknown step as unreviewed.
    :param should_stop: polled before every step; true cancels the run.
    :param on_context: called with the wired context before the run
        starts, so a caller can attach evidence and broker listeners.
    :return: the typed replay result.
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
        engine = context.settings.engine
        options = rooption.ReplayOptions(
            tenant=request.tenant or capability.default_tenant,
            params=dict(request.inputs or {}),
            inject_session_expiry_before=request.inject_session_expiry_before,
            total_timeout_s=engine.total_timeout_s,
            poll_interval_s=engine.poll_interval_s,
            recovery_budget=engine.recovery_budget,
            retry_delay_s=engine.retry_delay_s,
            settle_ms=engine.settle_ms,
            settle_short_ms=engine.settle_short_ms,
            goal_poll_s=engine.goal_poll_s,
            should_stop=should_stop or (lambda: False),
            edge_records=edge_records,
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
            max_invoke_depth=engine.max_invoke_depth,
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


def is_stable(result: results.ReplayResult) -> bool:
    """
    Whether a result counts toward a capability's track record.

    A success on a screen that drifted is working for now, but it counts
    against the capability: a person should look before it breaks.
    """
    drifted = isinstance(result, results.SuccessResult) and bool(result.drifted)
    return is_success(result) and not drifted


def counts_toward_stability(
    result: results.ReplayResult, *, cancelled: bool = False
) -> bool:
    """
    Whether a result says anything about the capability's health.

    A run someone stopped, a step a person refused, and a step nobody
    has reviewed yet are all decisions, not breakage.

    :param result: the replay's result.
    :param cancelled: the operator cancelled the run.
    :return: whether to record it.
    """
    decided = isinstance(result, results.FailureResult) and (
        result.failure.failure_class in _NOT_BREAKAGE
    )
    return not (cancelled or decided)
