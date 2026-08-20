"""
Deterministic replay of a compiled path - the orchestrator.

``replay_path`` runs the pre-flight checks (inputs, tenant, secret
resolution), executes each edge through ``EdgeExecutor``, asserts
arrival at the goal node, runs capability-scoped extraction, and returns
a typed ``ReplayResult``. No model decides anything here. Without an
approver every step that needs a human is denied - the safe default for
library callers.

Import as:

import operant.application.replay.engine as engine
"""

from __future__ import annotations

import collections.abc
import re
import time
from typing import Dict, List, Optional

import operant.adapters.secrets.env as env
import operant.application.approval as approval
import operant.application.escalation as escal
import operant.application.replay.context as context
import operant.application.replay.edge as reedge
import operant.application.replay.options as options
import operant.application.replay.outcomes as outcomes
import operant.application.replay.values as values
import operant.application.secrets as assecret
import operant.domain.events as events
import operant.domain.fingerprint as odfinger
import operant.domain.graph.localize as localize
import operant.domain.graph.pathfind as pathfind
import operant.domain.models.artifact as artifact
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import operant.domain.models.results as results
import operant.domain.models.targets as targets
import operant.domain.outcomes as dooutcom
import operant.domain.params as params
import operant.domain.redaction as redact
import operant.ports.evidence as evidence
import operant.ports.hitl as hitl
import operant.ports.secrets as pssecret
import operant.ports.surface as pssurfac

InvokeGraph = collections.abc.Callable[
    [graph.GraphRef, context.ReplayContext], Optional[results.ReplayResult]
]


def replay_path(
    capability: artifact.CapabilityArtifact,
    app_graph: graph.AppGraph,
    path: List[graph.Edge],
    surface: pssurfac.Surface,
    broker: escal.ControlBroker,
    log: evidence.EvidenceSink,
    redactor: redact.Redactor,
    opts: options.ReplayOptions,
    *,
    invoke_graph: Optional[InvokeGraph] = None,
    depth: int = 0,
    approver: Optional[hitl.Approver] = None,
    secret_store: Optional[pssecret.SecretStore] = None,
) -> results.ReplayResult:
    """
    Execute a chosen edge path and reports a typed result.

    :param capability: The capability being replayed.
    :param app_graph: The graph version it pins.
    :param path: The compiled edge path to run.
    :param surface: The actuation surface.
    :param broker: Control broker for hand-offs.
    :param log: Evidence sink.
    :param redactor: Masks sensitive values in evidence.
    :param opts: Inputs, tenant, and timing.
    :param invoke_graph: Cross-graph composition hook.
    :param depth: Composition depth of this run.
    :param approver: Who answers approvals; denies all when ``None``.
    :param secret_store: Where secret references resolve; env by
        default.
    :return: A success, business-outcome, escalated, or failure result.
    """
    precondition = _check_inputs(capability, opts, log, redactor)
    if precondition is not None:
        # Pre-flight rejected the inputs: stop before touching the app.
        result: results.ReplayResult = precondition
    else:
        # Inputs are valid: resolve the tenant, then run.
        tenant = capability.tenants.get(opts.tenant)
        if tenant is None:
            # No such tenant binding: fail fast.
            result = _unknown_tenant(capability, opts, log)
        else:
            # Tenant resolved: resolve secrets, build context, execute.
            store = secret_store or env.EnvSecretStore()
            secrets = assecret.SecretResolver(
                tenant, store, redactor
            ).resolve_available()
            ctx = _build_context(
                capability,
                app_graph,
                path,
                surface,
                broker,
                log,
                redactor,
                opts,
                tenant,
                secrets,
                approver,
                invoke_graph,
                depth,
            )
            _emit_started(ctx, path)
            result = _run(ctx, path)
    return result


def _run(
    ctx: context.ReplayContext, path: List[graph.Edge]
) -> results.ReplayResult:
    """
    Run the resolved path, unwinding on a decided terminal result.
    """

    def run_edge(edge: graph.Edge, *, allow_recovery: bool = True) -> None:
        reedge.EdgeExecutor(
            ctx,
            edge,
            allow_recovery=allow_recovery,
            run_edge=lambda prior: run_edge(prior, allow_recovery=False),
        ).execute()

    # Run the path, catching an edge that ends the run early.
    try:
        for edge in _resume_from_launch(ctx, path, run_edge):
            run_edge(edge)
        result = _finish(ctx)
    except context.Finished as done:
        result = done.result
    return result


def _resume_from_launch(
    ctx: context.ReplayContext,
    path: List[graph.Edge],
    run_edge: collections.abc.Callable[[graph.Edge], None],
) -> List[graph.Edge]:
    """
    Run a leading launch, then resume from the live state by content.

    After the launch we re-localize the live screen. When it is already
    past the recorded start (e.g. still logged in), we path-find
    straight to the goal and skip the recorded login edges; a logged-out
    replay localizes back to the launch's own destination and runs the
    recorded remainder unchanged.
    """
    resumed: List[graph.Edge] = path
    if path and path[0].action.kind == "launch":
        run_edge(path[0])
        remaining = path[1:]
        screen = ctx.surface.snapshot()
        current = localize.locate(screen, ctx.graph, ctx.opts.params)
        ctx.log.emit(
            events.Localized(
                node=current,
                window=screen.window_title,
                summary=f"post-launch localized at node {current!r}",
            )
        )
        if current is None or current == path[0].to_node:
            # Logged out or at the recorded start: run the rest as-is.
            resumed = remaining
        elif current == ctx.capability.goal_node:
            # Content matches the goal: resolve whether nav remains.
            resumed = _at_or_toward_goal(ctx, screen)
        else:
            # Somewhere past the start: replan a route to the goal.
            found = pathfind.shortest_path(
                ctx.graph, current, ctx.capability.goal_node
            )
            if found is None:
                # No route from here: fall back to the recorded rest.
                resumed = remaining
            else:
                # Route found: replay the replanned edges instead.
                ctx.log.emit(
                    events.PathPlanned(
                        path=[edge.id for edge in found],
                        start=current,
                        goal=ctx.capability.goal_node,
                        summary=(
                            f"resumed at {current}; replanned "
                            f"{len(found)} edge(s) past launch"
                        ),
                    )
                )
                resumed = found
    return resumed


_CLICKABLE = frozenset({"button", "link", "menu_item", "menuitem"})
_UNESCAPE = re.compile(r"\\(.)")


def _at_or_toward_goal(
    ctx: context.ReplayContext, screen: digest.ScreenDigest
) -> List[graph.Edge]:
    """
    Resolve a content match against the goal node into a plan.

    The live screen's content matched the goal node, but titles and URLs
    repeat: an app's logged-in landing can look like the account page
    (shared menu) without being it. When the goal node's own checks hold
    we are truly there and nothing remains; otherwise we are adjacent -
    on a look-alike that carries a live link named after the goal - so we
    click that link to actually arrive, then the goal assertion runs.
    """
    goal_node = ctx.graph.node(ctx.capability.goal_node)
    checks = [
        params.substitute_condition(c, ctx.opts.params) for c in goal_node.checks
    ]
    plan: List[graph.Edge]
    if dooutcom.on_node(checks, screen):
        # Goal checks hold: we are truly there, nothing remains.
        plan = []
    else:
        # A look-alike adjacent to the goal: find a link toward it.
        nav = _affordance_toward(ctx, screen, goal_node)
        if nav is None:
            # Nothing names the goal: treat as already arrived.
            plan = []
        else:
            # Found the link: plan a single click onto it.
            ctx.log.emit(
                events.PathPlanned(
                    path=[nav.id],
                    start=goal_node.id,
                    goal=goal_node.id,
                    summary=(
                        f"adjacent to goal; navigating via "
                        f'"{nav.description}" to reach it'
                    ),
                )
            )
            plan = [nav]
    return plan


def _affordance_toward(
    ctx: context.ReplayContext,
    screen: digest.ScreenDigest,
    goal_node: graph.Node,
) -> Optional[graph.Edge]:
    """
    Build a click edge onto the live link that reaches ``goal_node``.

    The goal page names itself in its own nav (a menu link whose text is
    the page title); the same link sits on adjacent pages. We pick the
    live clickable control whose name is the longest run contained in
    the goal's title, so "Accounts Overview" wins over a bare "ParaBank"
    home link, and ``None`` when nothing names the goal.
    """
    title = _goal_title(goal_node)
    edge: Optional[graph.Edge] = None
    if title:
        best: Optional[digest.Control] = None
        best_len = 0
        for control in screen.controls:
            if control.role.lower() not in _CLICKABLE or not control.name:
                continue
            name = odfinger.normalize(control.name)
            if name and name in title and len(name) > best_len:
                best, best_len = control, len(name)
        if best is not None:
            target = targets.Target(
                strategies=[targets.RoleStrategy(role=best.role, name=best.name)],
                reasoning=f'"{best.name}" navigates to the goal page',
            )
            edge = graph.Edge.model_validate(
                {
                    "id": "resume-nav",
                    "from": goal_node.id,
                    "to": goal_node.id,
                    "description": best.name,
                    "action": {"kind": "click"},
                    "target": target.model_dump(),
                    "wait": {"kind": "settle", "timeout_ms": 4000},
                    "risk": "safe",
                }
            )
    return edge


def _goal_title(goal_node: graph.Node) -> str:
    """
    Return the normalized title pattern from the goal's checks.
    """
    title = ""
    for check in goal_node.checks:
        if isinstance(check, graph.TitleMatches):
            title = odfinger.normalize(_UNESCAPE.sub(r"\1", check.pattern))
            break
    return title


def _finish(ctx: context.ReplayContext) -> results.ReplayResult:
    """
    Assert the goal, extract declared outputs, and report success.
    """
    capability = ctx.capability
    arrived, screen = outcomes.poll_node(
        ctx, capability.goal_node, ctx.opts.goal_poll_s
    )
    if not arrived:
        raise outcomes.fail(
            ctx,
            None,
            "node_assert_failed",
            f"goal node {capability.goal_node} checks hold",
            f'window "{screen.window_title}"',
        )
    if capability.extract:
        _extract_declared(ctx, screen)
    ctx.log.screenshot(ctx.surface, "success")
    ctx.log.emit(
        events.ReplayFinished(
            status="success",
            outputs=ctx.outputs,
            summary=f"success; outputs: {ctx.outputs}",
        )
    )
    result = results.SuccessResult(
        outputs=ctx.outputs, evidence_dir=str(ctx.log.dir)
    )
    return result


def _extract_declared(
    ctx: context.ReplayContext,
    goal_screen: digest.ScreenDigest,
) -> None:
    """
    Extract declared outputs at the goal or extraction node.
    """
    capability = ctx.capability
    at_goal = (
        not capability.extract_at_node
        or capability.extract_at_node == capability.goal_node
    )
    src = goal_screen if at_goal else ctx.extract_digest
    if src is None:
        raise outcomes.fail(
            ctx,
            None,
            "node_assert_failed",
            f"screen at extract_at_node {capability.extract_at_node}",
            "extraction node was never reached on this path",
        )
    extracted, missing = dooutcom.run_extraction(capability.extract, src)
    values.record_outputs(ctx, extracted)
    node = capability.extract_at_node or capability.goal_node
    ctx.log.emit(
        events.OutputsExtracted(
            node=node,
            outputs=extracted,
            missing=missing,
            summary=f"extracted {', '.join(extracted) or 'nothing'} at {node}",
        )
    )
    if missing:
        raise outcomes.fail(
            ctx,
            None,
            "node_assert_failed",
            f"extractable outputs: {missing}",
            "declared outputs not present at the extraction node",
        )


def _check_inputs(
    capability: artifact.CapabilityArtifact,
    opts: options.ReplayOptions,
    log: evidence.EvidenceSink,
    redactor: redact.Redactor,
) -> Optional[results.ReplayResult]:
    """
    Validate required inputs and register sensitive ones for redaction.
    """
    failure: Optional[results.ReplayResult] = None
    for name, spec in capability.inputs.items():
        if spec.required and name not in opts.params:
            failure = results.FailureResult(
                failure=results.Failure(
                    at_edge="(inputs)",
                    failure_class="precondition_failed",
                    expected=f'input "{name}" provided',
                    observed="missing",
                    evidence_refs=[],
                ),
                evidence_dir=str(log.dir),
            )
            break
        if spec.sensitive or spec.data_class != "none":
            redactor.add_secret(opts.params.get(name))
    return failure


def _unknown_tenant(
    capability: artifact.CapabilityArtifact,
    opts: options.ReplayOptions,
    log: evidence.EvidenceSink,
) -> results.ReplayResult:
    """
    Build the failure result for an unknown tenant.
    """
    result = results.FailureResult(
        failure=results.Failure(
            at_edge="(tenant)",
            failure_class="precondition_failed",
            expected=f"one of {sorted(capability.tenants)}",
            observed=f'unknown tenant "{opts.tenant}"',
            evidence_refs=[],
        ),
        evidence_dir=str(log.dir),
    )
    return result


def _build_context(
    capability: artifact.CapabilityArtifact,
    app_graph: graph.AppGraph,
    path: List[graph.Edge],
    surface: pssurfac.Surface,
    broker: escal.ControlBroker,
    log: evidence.EvidenceSink,
    redactor: redact.Redactor,
    opts: options.ReplayOptions,
    tenant: artifact.TenantBinding,
    secrets: Dict[str, str],
    approver: Optional[hitl.Approver],
    invoke_graph: Optional[InvokeGraph],
    depth: int,
) -> context.ReplayContext:
    """
    Assemble the replay context for this run.
    """
    ctx = context.ReplayContext(
        capability=capability,
        graph=app_graph,
        surface=surface,
        broker=broker,
        log=log,
        opts=opts,
        base_url=tenant.base_url.rstrip("/"),
        secrets=secrets,
        approver=approver or approval.DenyAllApprover(),
        redactor=redactor,
        path=path,
        output_origins=dict(opts.output_origins),
        deadline=time.monotonic() + opts.total_timeout_s,
        invoke_graph=invoke_graph,
        depth=depth,
    )
    return ctx


def _emit_started(ctx: context.ReplayContext, path: List[graph.Edge]) -> None:
    """
    Emit the replay-started event for this path.
    """
    ids = [e.id for e in path]
    capability = ctx.capability
    ctx.log.emit(
        events.ReplayStarted(
            capability=capability.id,
            version=capability.version,
            graph_version=capability.graph_version,
            tenant=ctx.opts.tenant,
            params=ctx.opts.params,
            path=ids,
            summary=(
                f"replaying {capability.id} v{capability.version} on graph "
                f"v{capability.graph_version}, tenant {ctx.opts.tenant}, "
                f"path {ids}"
            ),
        )
    )
