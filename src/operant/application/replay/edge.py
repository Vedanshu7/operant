"""
Executing one graph edge deterministically.

``EdgeExecutor`` runs a single edge in the fixed order the whole system
depends on: deadline check, interrupt scan, optional fault injection,
build the concrete action (resolving its target via ranked strategies),
policy/approval choke point, settle wait, and finally the arrival assert
at the destination node. Outcome edges are consulted only when something
is off, and the built-in recovery paths retry the edge from the resumed
state. No LLM anywhere.

Import as:

import operant.application.replay.edge as reedge
"""

from __future__ import annotations

import time
from typing import List, Optional

import operant.application.actions as actions
import operant.application.approval as approval
import operant.application.replay.context as context
import operant.application.replay.outcomes as outcomes
import operant.application.replay.values as values
import operant.domain.errors as errors
import operant.domain.events as events
import operant.domain.locate as locate
import operant.domain.models.actions as maaction
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import operant.domain.models.targets as targets
import operant.domain.params as params

_ARRIVAL_FLOOR_MS = 4000
_SETTLE_CAP_MS = 2000
_HUMAN_ASSIST_POLL_S = 4.0
_HUMAN_ARRIVAL_POLL_S = 5.0


# #############################################################################
# EdgeExecutor
# #############################################################################


class EdgeExecutor:
    """
    Run one edge, with recovery and escalation, against a context.
    """

    def __init__(
        self,
        ctx: context.ReplayContext,
        edge: graph.Edge,
        *,
        allow_recovery: bool,
        run_edge: outcomes.RunEdge,
    ) -> None:
        self._ctx = ctx
        self._edge = edge
        self._allow_recovery = allow_recovery
        self._run_edge = run_edge
        self._factory = actions.ActionFactory()
        self._budget = outcomes.Budget(left=ctx.opts.recovery_budget)

    def execute(self) -> None:
        """
        Run the edge from the top, honouring interrupts and the deadline.
        """
        ctx, edge = self._ctx, self._edge
        if time.monotonic() > ctx.deadline:
            raise outcomes.fail(
                ctx,
                edge,
                "timeout",
                f"run under {ctx.opts.total_timeout_s}s",
                "total run deadline exceeded",
            )
        if self._allow_recovery:
            outcomes.scan_interrupts(ctx)
        self._maybe_inject_fault()
        self._attempt()

    def _maybe_inject_fault(self) -> None:
        """
        Inject a session-expiry fault before this edge when configured.
        """
        ctx, edge = self._ctx, self._edge
        if ctx.opts.inject_session_expiry_before != edge.id:
            return
        ctx.opts.inject_session_expiry_before = None
        ctx.log.emit(
            _fault_event(edge.id),
        )
        ctx.surface.inject_session_expiry()

    def _consult(self, screen: digest.ScreenDigest, node_id: str) -> bool:
        """
        Consult outcome edges at ``node_id`` for the current screen.
        """
        handled = outcomes.consult_outcome_edges(
            self._ctx,
            self._edge,
            screen,
            node_id,
            self._attempt,
            self._budget,
            self._run_edge,
            allow_recovery=self._allow_recovery,
        )
        return handled

    def _attempt(self) -> None:
        """
        Attempt the edge: dispatch invoke, or build, perform, assert.
        """
        if self._edge.action.kind == "invoke":
            # An invoke edge: delegate to the nested graph run.
            self._attempt_invoke()
        else:
            # A surface edge: build it, perform it, assert arrival.
            action = self._build_action()
            if action is not None:
                self._perform(action)
                self._await_arrival()

    def _attempt_invoke(self) -> None:
        """
        Run an invoke edge, bubbling any nested terminal result.
        """
        ctx, edge = self._ctx, self._edge
        ref = edge.action.graph_ref
        if ref is None or ctx.invoke_graph is None:
            raise outcomes.fail(
                ctx,
                edge,
                "precondition_failed",
                "invoke edge has a graph_ref and an invoker",
                "missing graph_ref or invoker",
            )
        ctx.log.emit(_invoke_event(edge, ref))
        result = ctx.invoke_graph(ref, ctx)
        if result is not None:
            raise context.Finished(result)
        self._assert_arrival_after_invoke(ref)

    def _assert_arrival_after_invoke(self, ref: graph.GraphRef) -> None:
        """
        Assert arrival at the destination after an invoke returns.
        """
        ctx, edge = self._ctx, self._edge
        arrived, screen = outcomes.poll_node(
            ctx,
            edge.to_node,
            max(edge.wait.timeout_ms, _ARRIVAL_FLOOR_MS) / 1000,
        )
        if not arrived and not self._consult(screen, edge.to_node):
            raise outcomes.fail(
                ctx,
                edge,
                "node_assert_failed",
                f"node {edge.to_node} after invoking {ref.graph_id}",
                f'window "{screen.window_title}"',
            )
        self._capture_extract_node(edge.to_node, screen)

    def _build_action(self) -> Optional[maaction.SurfaceAction]:
        """
        Build the surface action, or ``None`` when a recovery handled it.
        """
        edge = self._edge
        kind = edge.action.kind
        action: Optional[maaction.SurfaceAction]
        if kind == "launch":
            action = self._launch_action()
        elif kind == "press":
            action = self._factory.press(
                edge.action.key or "Enter", step=edge.id
            ).surface
        elif kind == "scroll" and edge.target is None:
            action = self._factory.scroll(
                None,
                edge.action.direction or "down",
                edge.action.amount or 1,
                step=edge.id,
            ).surface
        else:
            action = self._resolved_action()
        return action

    def _launch_action(self) -> maaction.SurfaceAction:
        """
        Build the launch action, absolutizing a relative URL.
        """
        edge = self._edge
        url = edge.action.url or "/"
        full = url if url.startswith("http") else f"{self._ctx.base_url}{url}"
        action = self._factory.launch(edge.action.app, full, step=edge.id).surface
        return action

    def _resolved_action(self) -> Optional[maaction.SurfaceAction]:
        """
        Resolve the edge's target and build its action, retrying once.
        """
        ctx, edge = self._ctx, self._edge
        if edge.target is None:
            raise outcomes.fail(
                ctx,
                edge,
                "precondition_failed",
                "edge has a target",
                "target missing in artifact",
            )
        strategies = params.substitute_strategies(
            edge.target.strategies, ctx.opts.params
        )
        screen = ctx.surface.snapshot()
        resolution = locate.resolve_target(strategies, screen)
        if not isinstance(resolution, locate.Resolution):
            time.sleep(ctx.opts.retry_delay_s)
            screen = ctx.surface.snapshot()
            resolution = locate.resolve_target(strategies, screen)
        action: Optional[maaction.SurfaceAction]
        if isinstance(resolution, locate.Resolution):
            action = self._action_for(resolution)
        else:
            action = self._on_unresolved(strategies, screen, resolution)
        return action

    def _action_for(
        self, resolution: locate.Resolution
    ) -> maaction.SurfaceAction:
        """
        Build the concrete action for a resolved control.
        """
        ctx, edge = self._ctx, self._edge
        ctx.log.emit(_resolved_event(edge, resolution))
        ref = resolution.control.ref
        kind = edge.action.kind
        action: maaction.SurfaceAction
        if kind == "click":
            action = self._factory.click(ref, step=edge.id).surface
        elif kind == "select":
            text, data_class, export_from, secret_ref = values.resolve_value(
                edge.action.option or targets.Value(literal=""), ctx
            )
            action = maaction.SurfaceAction(
                kind="select",
                ref=ref,
                option=text,
                data_class=data_class,
                export_from=export_from,
                secret_ref=secret_ref,
                step=edge.id,
            )
        elif kind == "scroll":
            action = maaction.SurfaceAction(
                kind="scroll",
                ref=ref,
                direction=edge.action.direction,
                amount=edge.action.amount,
                step=edge.id,
            )
        else:
            text, data_class, export_from, secret_ref = values.resolve_value(
                edge.action.value or targets.Value(literal=""), ctx
            )
            action = maaction.SurfaceAction(
                kind="fill",
                ref=ref,
                value=text,
                data_class=data_class,
                export_from=export_from,
                secret_ref=secret_ref,
                step=edge.id,
            )
        return action

    def _on_unresolved(
        self,
        strategies: List[targets.TargetStrategy],
        screen: digest.ScreenDigest,
        resolution: locate.ResolutionFailure,
    ) -> Optional[maaction.SurfaceAction]:
        """
        Handle an unresolved target: region-click, consult, or recover.
        """
        ctx, edge = self._ctx, self._edge
        first = strategies[0] if strategies else None
        action: Optional[maaction.SurfaceAction]
        if (
            edge.action.kind == "click"
            and isinstance(first, targets.RegionStrategy)
            and all(isinstance(s, targets.RegionStrategy) for s in strategies)
        ):
            # Pure region target: click its centre point blind.
            action = maaction.SurfaceAction(
                kind="click",
                x=first.x + first.w / 2,
                y=first.y + first.h / 2,
                target_text=edge.description,
                step=edge.id,
            )
        elif self._consult(screen, edge.from_node):
            # An outcome edge handled the miss: nothing to perform.
            action = None
        else:
            # Genuinely unresolved: report, then recover or fail.
            self._report_locator_failure(resolution)
            if self._allow_recovery:
                self._recover_locator(resolution)
                action = None
            else:
                kind = first.kind if first else "unknown"
                raise outcomes.fail(
                    ctx,
                    edge,
                    f"locator_{resolution.error}",  # type: ignore[arg-type]
                    f"unique control for {kind} strategy",
                    f"tried: {resolution.tried}",
                )
        return action

    def _report_locator_failure(
        self, resolution: locate.ResolutionFailure
    ) -> None:
        """
        Log the locator failure with a screenshot.
        """
        ctx, edge = self._ctx, self._edge
        shot = ctx.log.screenshot(ctx.surface, f"locator-failed-{edge.id}")
        ctx.log.emit(_locator_failed_event(edge, resolution, shot))

    def _recover_locator(
        self, resolution: locate.ResolutionFailure
    ) -> Optional[maaction.SurfaceAction]:
        """
        Escalate an unresolved locator, then retry after human assist.
        """
        ctx, edge = self._ctx, self._edge
        outcomes.escalate(
            ctx, edge, f"target could not be resolved ({resolution.error})"
        )
        arrived, _ = outcomes.poll_node(ctx, edge.to_node, _HUMAN_ASSIST_POLL_S)
        if arrived:
            ctx.broker.resume_automation(f"{edge.id} completed by operator")
        else:
            ctx.broker.resume_automation(f"retrying {edge.id} after human assist")
            self._attempt()
        return None

    def _perform(self, action: maaction.SurfaceAction) -> None:
        """
        Perform the action through the approval gate, classifying errors.
        """
        ctx, edge = self._ctx, self._edge
        try:
            gated = approval.perform_gated(
                ctx.surface,
                action,
                approver=ctx.approver,
                log=ctx.log,
                run_id=ctx.log.run_id,
            )
            ctx.deadline += gated.waited_s
        except errors.ApprovalDeniedError as denied:
            raise outcomes.fail(
                ctx,
                edge,
                "approval_denied",
                f"human approval for {denied.request.kind}: "
                f"{denied.request.summary}",
                f"{denied.decision.by}: "
                f"{denied.decision.note or 'not approved'}",
            ) from denied
        except errors.PolicyViolationError as violation:
            raise outcomes.fail(
                ctx,
                edge,
                "policy_violation",
                "action within policy",
                violation.decision.reason,
            ) from violation
        except context.Finished:
            raise
        # The gateway wraps tool failures.
        except Exception as err:
            raise outcomes.fail(
                ctx,
                edge,
                "app_error",
                "the gateway performs the action",
                f"{type(err).__name__}: {err}",
            ) from err
        ctx.log.emit(_performed_event(edge))

    def _await_arrival(self) -> None:
        """
        Wait for arrival, then extract or handle a miss.
        """
        ctx, edge = self._ctx, self._edge
        if edge.wait.kind == "settle":
            time.sleep(min(edge.wait.timeout_ms, _SETTLE_CAP_MS) / 1000)
        arrived, screen = outcomes.poll_node(
            ctx,
            edge.to_node,
            max(edge.wait.timeout_ms, _ARRIVAL_FLOOR_MS) / 1000,
        )
        if not arrived:
            self._handle_missed_arrival(screen)
        else:
            self._capture_extract_node(edge.to_node, screen)

    def _handle_missed_arrival(self, screen: digest.ScreenDigest) -> None:
        """
        Consult outcome edges on a missed arrival, else escalate or fail.
        """
        ctx, edge = self._ctx, self._edge
        if self._consult(screen, edge.to_node) or self._consult(
            screen, edge.from_node
        ):
            return
        shot = ctx.log.screenshot(ctx.surface, f"node-assert-failed-{edge.id}")
        ctx.log.emit(_node_assert_failed_event(edge, shot))
        if self._allow_recovery:
            outcomes.escalate(
                ctx,
                edge,
                f'expected to reach "{edge.to_node}" but its checks never held',
            )
            arrived_after, _ = outcomes.poll_node(
                ctx, edge.to_node, _HUMAN_ARRIVAL_POLL_S
            )
            if arrived_after:
                ctx.broker.resume_automation(
                    f"node {edge.to_node} reached after human assist"
                )
                return
        raise outcomes.fail(
            ctx,
            edge,
            "node_assert_failed",
            f"node {edge.to_node} checks hold",
            f'window "{screen.window_title}"; text: {screen.text[:200]}',
        )

    def _capture_extract_node(
        self, node_id: str, screen: digest.ScreenDigest
    ) -> None:
        """
        Capture and eagerly extract when this is the extract node.
        """
        ctx = self._ctx
        if node_id == ctx.capability.extract_at_node:
            ctx.extract_digest = screen
            values.extract_eagerly(ctx, screen)


def _fault_event(edge_id: str) -> events.BaseEvent:
    """
    Build the fault-injected event for an edge.
    """
    event = events.FaultInjected(
        edge=edge_id,
        fault="session-expired",
        summary=f"restarting app container before {edge_id} (real infra fault)",
    )
    return event


def _invoke_event(edge: graph.Edge, ref: graph.GraphRef) -> events.BaseEvent:
    """
    Build the invoke-graph event for an edge.
    """
    event = events.InvokeGraph(
        edge=edge.id,
        graph=ref.graph_id,
        version=ref.version,
        target=ref.target_node,
        summary=f"{edge.id}: invoke graph {ref.graph_id}",
    )
    return event


def _resolved_event(
    edge: graph.Edge, resolution: locate.Resolution
) -> events.BaseEvent:
    """
    Build the target-resolved event for an edge.
    """
    event = events.TargetResolved(
        edge=edge.id,
        strategy=resolution.strategy_kind,
        index=resolution.strategy_index,
        summary=(
            f"resolved {edge.id} via "
            f"{resolution.strategy_kind}[{resolution.strategy_index}]"
        ),
    )
    return event


def _locator_failed_event(
    edge: graph.Edge, resolution: locate.ResolutionFailure, shot: str
) -> events.BaseEvent:
    """
    Build the locator-failed event for an edge.
    """
    event = events.LocatorFailed(
        edge=edge.id,
        tried=list(resolution.tried),
        screenshot=shot,
        summary=f"could not resolve target for {edge.id}",
    )
    return event


def _performed_event(edge: graph.Edge) -> events.BaseEvent:
    """
    Build the action-performed event for an edge.
    """
    event = events.ActionPerformed(
        edge=edge.id,
        kind=edge.action.kind,
        summary=f"{edge.id}: {edge.description}",
    )
    return event


def _node_assert_failed_event(edge: graph.Edge, shot: str) -> events.BaseEvent:
    """
    Build the node-assert-failed event for an edge.
    """
    event = events.NodeAssertFailed(
        edge=edge.id,
        node=edge.to_node,
        screenshot=shot,
        summary=f"did not arrive at node {edge.to_node}",
    )
    return event
