"""
Outcome-edge handling, escalation, interrupts, and node polling.

These helpers implement the exceptional-state half of replay: polling
for node arrival, matching and applying outcome edges (the business-
outcome / recover / escalate / fail / invoke taxonomy), firing global
interrupt bindings, escalating to a human, and building a classified
failure. The happy per-edge path lives in ``edge``; these are consulted
only when something is off, so a detector cannot fire while the flow is
on its recorded path.

Import as:

import operant.application.replay.outcomes as outcomes
"""

from __future__ import annotations

import collections.abc
import dataclasses
import time
from typing import Optional, Tuple

import operant.application.escalation as escal
import operant.application.replay.context as context
import operant.domain.events as events
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import operant.domain.models.results as results
import operant.domain.outcomes as outcomes
import operant.domain.params as params

RunEdge = collections.abc.Callable[[graph.Edge], None]
Retry = collections.abc.Callable[[], None]


# #############################################################################
# Budget
# #############################################################################


@dataclasses.dataclass
class Budget:
    """
    The recover/escalate allowance left for one edge execution.

    :ivar left: Remaining outcome-edge recoveries before the run hard-
        fails.
    """

    left: int


def poll_node(
    ctx: context.ReplayContext, node_id: str, timeout_s: float
) -> Tuple[bool, digest.ScreenDigest]:
    """
    Poll until the node's checks hold or the timeout lapses.

    :param ctx: The active replay context.
    :param node_id: Node whose checks must hold.
    :param timeout_s: How long to poll before giving up.
    :return:``(arrived, last screen digest)``.
    """
    node = ctx.graph.node(node_id)
    checks = [
        params.substitute_condition(c, ctx.opts.params) for c in node.checks
    ]
    deadline = time.monotonic() + timeout_s
    screen = ctx.surface.snapshot()
    arrived = outcomes.on_node(checks, screen)
    while not arrived:
        if time.monotonic() > deadline:
            break
        time.sleep(ctx.opts.poll_interval_s)
        screen = ctx.surface.snapshot()
        arrived = outcomes.on_node(checks, screen)
    return arrived, screen


def fail(
    ctx: context.ReplayContext,
    edge: Optional[graph.Edge],
    failure_class: results.FailureClass,
    expected: str,
    observed: str,
) -> context.Finished:
    """
    Build a classified failure and the ``Finished`` that ends the run.

    :param ctx: The active replay context.
    :param edge: The edge that failed, or ``None`` for a run-level
        failure.
    :param failure_class: Closed failure vocabulary entry.
    :param expected: What replay expected.
    :param observed: What replay observed instead.
    :return: A ``Finished`` carrying the ``FailureResult``; raise it.
    """
    at_edge = edge.id if edge else "run"
    shot = ctx.log.screenshot(ctx.surface, f"failure-{at_edge}")
    result = results.FailureResult(
        failure=results.Failure(
            at_edge=edge.id if edge else "(run)",
            failure_class=failure_class,
            expected=expected,
            observed=observed,
            evidence_refs=[shot],
        ),
        evidence_dir=str(ctx.log.dir),
    )
    ctx.log.emit(
        events.ReplayFinished(
            status="failure",
            summary=f"failure at {result.failure.at_edge}: {failure_class}",
        )
    )
    finished = context.Finished(result)
    return finished


def _snapshot_title(ctx: context.ReplayContext) -> str:
    """
    Return the window title, logging a surface error if wedged.
    """
    try:
        title = ctx.surface.snapshot().window_title
    except Exception as err:
        ctx.log.emit(events.SurfaceError(error=str(err)))
        title = ""
    return title


def escalate(
    ctx: context.ReplayContext,
    edge: Optional[graph.Edge],
    reason: str,
) -> None:
    """
    Hand control to a human and blocks until they resolve it.

    On a hand-back the run continues and the real intervention id is
    recorded for the escalated result; on abandonment the run ends.

    :param ctx: The active replay context.
    :param edge: The edge in trouble, or ``None`` for a run-level
        escalation.
    :param reason: Why a human is needed.
    """
    at = edge.id if edge else "run"
    shot = ctx.log.screenshot(ctx.surface, f"escalation-{at}")
    ctx.log.emit(
        events.EscalationRaised(
            edge=edge.id if edge else None,
            reason=reason,
            screenshot=shot,
            summary=f"escalating: {reason}",
        )
    )
    paused_at = time.monotonic()
    request = escal.InterventionRequest(
        run_id=ctx.log.run_id,
        kind="replay",
        capability=ctx.capability.name,
        goal=ctx.capability.provenance.goal,
        reason=reason,
        page_title=_snapshot_title(ctx),
        edge_id=edge.id if edge else None,
        screenshot_file=shot,
    )
    resolution = ctx.broker.raise_intervention(request)
    ctx.deadline += time.monotonic() - paused_at
    ctx.log.emit(
        events.EscalationResolved(
            resolution=resolution.resolution,
            note=resolution.note,
            human_actions=resolution.human_actions,
            summary=(
                f"operator {resolution.resolution} "
                f"({len(resolution.human_actions)} recorded actions)"
            ),
        )
    )
    if resolution.resolution == "abandoned":
        raise context.Finished(
            results.EscalatedResult(
                intervention_id=request.id,
                resolution="abandoned",
                evidence_dir=str(ctx.log.dir),
            )
        )
    ctx.intervention_id = request.id


def scan_interrupts(ctx: context.ReplayContext) -> None:
    """
    Fire global (``at='*'``) invoke bindings whose trigger holds now.

    Each binding fires at most once per run; a terminal nested result
    bubbles via ``Finished``.

    :param ctx: The active replay context.
    """
    bindings = [
        o
        for o in ctx.graph.outcome_edges
        if o.at == "*"
        and o.handle.type == "invoke"
        and o.id not in ctx.fired_bindings
    ]
    if not bindings or ctx.invoke_graph is None:
        return
    screen = ctx.surface.snapshot()
    for binding in bindings:
        when = params.substitute_condition(binding.when, ctx.opts.params)
        if not outcomes.evaluate_condition(when, screen):
            continue
        ctx.fired_bindings.add(binding.id)
        handle = binding.handle
        if not isinstance(handle, graph.InvokeGraphHandle):
            continue
        ref = handle.ref
        ctx.log.emit(
            events.InterruptFired(
                binding=binding.id,
                graph=ref.graph_id,
                summary=f"interrupt {binding.id} -> invoke {ref.graph_id}",
            )
        )
        result = ctx.invoke_graph(ref, ctx)
        if result is not None:
            raise context.Finished(result)


def consult_outcome_edges(
    ctx: context.ReplayContext,
    edge: graph.Edge,
    screen: digest.ScreenDigest,
    node_id: str,
    retry: Retry,
    budget: Budget,
    run_edge: RunEdge,
    *,
    allow_recovery: bool,
) -> bool:
    """
    Apply the first outcome edge matching at ``node_id``, if any.

    :param ctx: The active replay context.
    :param edge: The edge being executed.
    :param screen: The digest to test detectors against.
    :param node_id: The node the run is considered at.
    :param retry: Re-runs the blocked edge from the resumed state.
    :param budget: The recovery allowance for this edge.
    :param run_edge: Runs one safe prefix edge (used by re-login
        recovery).
    :param allow_recovery: Whether recovery is permitted on this
        attempt.
    :return:``True`` when an outcome edge was matched and handled.
    """
    matched = outcomes.match_outcome_edges(
        ctx.graph.outcome_edges, node_id, screen
    )
    handled = False
    if matched and allow_recovery:
        handle_outcome_edge(ctx, edge, matched, retry, budget, run_edge)
        handled = True
    return handled


def handle_outcome_edge(
    ctx: context.ReplayContext,
    edge: graph.Edge,
    matched: graph.OutcomeEdge,
    retry: Retry,
    budget: Budget,
    run_edge: RunEdge,
) -> None:
    """
    Apply a matched outcome edge; returns to continue, raises to end.

    :param ctx: The active replay context.
    :param edge: The edge being executed.
    :param matched: The outcome edge whose condition held.
    :param retry: Re-runs the blocked edge from the resumed state.
    :param budget: The recovery allowance for this edge.
    :param run_edge: Runs one safe prefix edge (used by re-login
        recovery).
    """
    handle = matched.handle
    ctx.log.emit(
        events.OutcomeEdgeMatched(
            edge=edge.id,
            outcome_edge=matched.id,
            handle=handle.type,
            summary=f"{matched.id} -> {handle.type}",
        )
    )
    if handle.type in {"recover", "escalate"}:
        _spend_budget(ctx, edge, matched, budget)
    if handle.type == "business_outcome":
        _end_business_outcome(ctx, matched)
    if handle.type == "fail":
        raise fail(
            ctx,
            edge,
            handle.failure_class,
            "no failure condition present",
            handle.message or f"outcome edge {matched.id} matched",
        )
    if handle.type == "escalate":
        escalate(ctx, edge, handle.reason)
        retry()
        return
    if handle.type == "invoke":
        _handle_invoke(ctx, edge, matched, retry)
        return
    if isinstance(handle, graph.RecoverHandle):
        _handle_recover(ctx, edge, handle, retry, run_edge)


def _spend_budget(
    ctx: context.ReplayContext,
    edge: graph.Edge,
    matched: graph.OutcomeEdge,
    budget: Budget,
) -> None:
    """
    Decrements the recovery budget, hard-failing when it runs out.
    """
    budget.left -= 1
    if budget.left < 0:
        raise fail(
            ctx,
            edge,
            "app_error",
            "exceptional condition resolves after recovery",
            f"outcome edge {matched.id} matched repeatedly; "
            "recovery budget exhausted",
        )


def _end_business_outcome(
    ctx: context.ReplayContext, matched: graph.OutcomeEdge
) -> None:
    """
    End the run with the application-reported business outcome.
    """
    handle = matched.handle
    assert isinstance(handle, graph.BusinessOutcomeHandle)  # noqa: S101
    ctx.log.screenshot(ctx.surface, f"outcome-{handle.outcome}")
    ctx.log.emit(
        events.ReplayFinished(
            status="business_outcome",
            summary=f"business outcome: {handle.outcome}",
        )
    )
    raise context.Finished(
        results.BusinessOutcomeResult(
            outcome=handle.outcome,
            detail=handle.detail or matched.id,
            evidence_dir=str(ctx.log.dir),
        )
    )


def _handle_invoke(
    ctx: context.ReplayContext,
    edge: graph.Edge,
    matched: graph.OutcomeEdge,
    retry: Retry,
) -> None:
    """
    Run a bound graph for a fired binding, then retries the edge.
    """
    handle = matched.handle
    assert isinstance(handle, graph.InvokeGraphHandle)  # noqa: S101
    if ctx.invoke_graph is None:
        raise fail(
            ctx,
            edge,
            "app_error",
            "an invoker for binding edges",
            "no invoker configured",
        )
    ctx.log.emit(
        events.InvokeGraph(
            edge=edge.id,
            graph=handle.ref.graph_id,
            binding=matched.id,
            summary=(
                f"binding {matched.id} -> invoke graph {handle.ref.graph_id}"
            ),
        )
    )
    result = ctx.invoke_graph(handle.ref, ctx)
    if result is not None:
        raise context.Finished(result)
    retry()


def _handle_recover(
    ctx: context.ReplayContext,
    edge: graph.Edge,
    handle: graph.RecoverHandle,
    retry: Retry,
    run_edge: RunEdge,
) -> None:
    """
    Apply a built-in recovery, then retries the blocked edge.
    """
    if handle.recovery == "dismissDialog":
        return
    if handle.recovery == "retryEdge":
        time.sleep(ctx.opts.retry_delay_s)
        retry()
        return
    ctx.log.emit(
        events.RecoveryRelogin(
            edge=edge.id,
            summary="session lost - re-running safe prefix of the path",
        )
    )
    for prior in ctx.path:
        if prior.id == edge.id:
            break
        if prior.risk == "safe":
            run_edge(prior)
    retry()
