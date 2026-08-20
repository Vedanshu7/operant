"""
Traversal replay: run a capability as a path query over the app graph.

Flow: observe -> localize -> choose a path (the cached compiled path
when the graph version matches, else path-find) -> execute via the per-
edge engine. When an edge or a fired interrupt binding invokes another
graph, the session retargets to that graph's window, a nested traversal
runs on the same live machine, then control returns and the caller
resumes.

Determinism comes from the compiled path; the invoke executor is depth-
guarded against runaway composition.

Import as:

import operant.application.replay.traverse as traverse
"""

from __future__ import annotations

import dataclasses
from typing import List, Optional, Union

import operant.application.escalation as escal
import operant.application.replay.context as context
import operant.application.replay.engine as engine
import operant.application.replay.options as options
import operant.domain.errors as errors
import operant.domain.events as events
import operant.domain.graph.localize as localize
import operant.domain.graph.pathfind as pathfind
import operant.domain.models.artifact as artifact
import operant.domain.models.graph as graph
import operant.domain.models.results as results
import operant.domain.redaction as redact
import operant.ports.evidence as evidence
import operant.ports.hitl as hitl
import operant.ports.repositories as repos
import operant.ports.surface as pssurfac

MAX_INVOKE_DEPTH = 4


def run_capability(
    capability: artifact.CapabilityArtifact,
    app_graph: graph.AppGraph,
    surface: pssurfac.Surface,
    broker: escal.ControlBroker,
    log: evidence.EvidenceSink,
    redactor: redact.Redactor,
    opts: options.ReplayOptions,
    *,
    depth: int = 0,
    graph_store: repos.GraphRepository,
    approver: Optional[hitl.Approver] = None,
    max_invoke_depth: int = MAX_INVOKE_DEPTH,
) -> results.ReplayResult:
    """
    Plan a path to the goal and replays it, composing across graphs.

    :param capability: The capability to run.
    :param app_graph: The pinned graph version.
    :param surface: The actuation surface.
    :param broker: Control broker for hand-offs.
    :param log: Evidence sink.
    :param redactor: Masks sensitive values in evidence.
    :param opts: Inputs, tenant, and timing.
    :param depth: Composition depth of this run.
    :param graph_store: Loads callee graphs for cross-domain invoke.
    :param approver: Who answers approvals.
    :param max_invoke_depth: Composition depth limit.
    :return: A typed replay result.
    """
    invoke = _make_invoker(
        capability,
        app_graph,
        surface,
        broker,
        log,
        redactor,
        opts,
        depth=depth,
        graph_store=graph_store,
        approver=approver,
        max_invoke_depth=max_invoke_depth,
    )
    planned = _plan_path(capability, app_graph, surface, log, opts)
    if not isinstance(planned, list):
        # Planning already resolved to a terminal result: return it.
        result = planned
    else:
        # A concrete edge path: replay it through the engine.
        result = engine.replay_path(
            capability,
            app_graph,
            planned,
            surface,
            broker,
            log,
            redactor,
            opts,
            invoke_graph=invoke,
            depth=depth,
            approver=approver,
        )
    return result


def _make_invoker(
    capability: artifact.CapabilityArtifact,
    app_graph: graph.AppGraph,
    surface: pssurfac.Surface,
    broker: escal.ControlBroker,
    log: evidence.EvidenceSink,
    redactor: redact.Redactor,
    opts: options.ReplayOptions,
    *,
    depth: int,
    graph_store: repos.GraphRepository,
    approver: Optional[hitl.Approver],
    max_invoke_depth: int,
) -> engine.InvokeGraph:
    """
    Build the cross-graph invoke hook for this run.
    """

    def invoke(
        ref: graph.GraphRef, parent_ctx: context.ReplayContext
    ) -> Optional[results.ReplayResult]:
        if depth + 1 > max_invoke_depth:
            raise errors.InvokeDepthExceededError(
                f"invoke depth exceeded ({max_invoke_depth})"
            )
        sub_graph = graph_store.get(ref.graph_id, ref.version)
        if ref.target_node is None:
            return _fail(log, f"invoke of {ref.graph_id} has no target_node")
        previous = surface.retarget(
            sub_graph.app_name or app_graph.app_name,
            sub_graph.window_title_pattern or app_graph.window_title_pattern,
        )
        log.emit(
            events.Retarget(
                to=f"{sub_graph.app_name}/{sub_graph.window_title_pattern}",
                summary=f"retarget session -> {sub_graph.vendor_id}",
            )
        )
        try:
            result = run_capability(
                _invoke_capability(capability, ref, sub_graph),
                sub_graph,
                surface,
                broker,
                log,
                redactor,
                _invoke_opts(opts, parent_ctx),
                depth=depth + 1,
                graph_store=graph_store,
                approver=approver,
                max_invoke_depth=max_invoke_depth,
            )
        finally:
            surface.retarget(*previous)
            log.emit(
                events.RetargetBack(
                    to=f"{previous[0]}/{previous[1]}",
                    summary="retarget session back to caller",
                )
            )
        return None if result.status == "success" else result

    return invoke


def _invoke_capability(
    caller: artifact.CapabilityArtifact,
    ref: graph.GraphRef,
    sub_graph: graph.AppGraph,
) -> artifact.CapabilityArtifact:
    """
    Synthesize the capability that drives a nested invoke.
    """
    cap = artifact.CapabilityArtifact(
        id=f"invoke:{ref.graph_id}",
        name=f"invoke {ref.graph_id}",
        description=f"cross-domain invoke into {ref.graph_id}",
        vendor_id=ref.graph_id,
        graph_version=sub_graph.graph_version,
        tenants=caller.tenants,
        default_tenant=caller.default_tenant,
        inputs={},
        outputs={},
        start_node="*",
        goal_node=ref.target_node or sub_graph.vendor_id,
        extract=[],
        compiled_path=[],
        policy_scope=caller.policy_scope,
        provenance=artifact.Provenance(**caller.provenance.model_dump()),
    )
    return cap


def _invoke_opts(
    opts: options.ReplayOptions,
    parent_ctx: Optional[context.ReplayContext],
) -> options.ReplayOptions:
    """
    Merge caller outputs into the options for a nested invoke.
    """
    if parent_ctx is None:
        # Top-level invoke: no caller outputs to fold in.
        merged = opts
    else:
        # Nested invoke: fold caller outputs and origins into params.
        merged = dataclasses.replace(
            opts,
            params={**opts.params, **parent_ctx.outputs},
            output_origins={
                **opts.output_origins,
                **parent_ctx.output_origins,
            },
        )
    return merged


def _plan_path(
    capability: artifact.CapabilityArtifact,
    app_graph: graph.AppGraph,
    surface: pssurfac.Surface,
    log: evidence.EvidenceSink,
    opts: options.ReplayOptions,
) -> Union[List[graph.Edge], results.ReplayResult]:
    launch_first = _leading_launch(capability, app_graph)
    planned: Optional[Union[List[graph.Edge], results.ReplayResult]] = None
    if (
        capability.compiled_path
        and capability.graph_version == app_graph.graph_version
    ):
        cached = pathfind.compiled_edges(app_graph, capability.compiled_path)
        if cached is not None and launch_first:
            log.emit(
                events.PathCompiledCache(
                    path=capability.compiled_path,
                    summary=f"using compiled path ({len(cached)} edges)",
                )
            )
            planned = cached
    if planned is None:
        planned = _plan_from_screen(
            capability, app_graph, surface, log, opts, launch_first=launch_first
        )
    return planned


def _plan_from_screen(
    capability: artifact.CapabilityArtifact,
    app_graph: graph.AppGraph,
    surface: pssurfac.Surface,
    log: evidence.EvidenceSink,
    opts: options.ReplayOptions,
    *,
    launch_first: bool,
) -> Union[List[graph.Edge], results.ReplayResult]:
    screen = surface.snapshot()
    current = localize.locate(screen, app_graph, opts.params)
    log.emit(
        events.Localized(
            node=current,
            window=screen.window_title,
            summary=f"localized at node {current!r}",
        )
    )
    result: Union[List[graph.Edge], results.ReplayResult]
    if current is None and launch_first and capability.compiled_path:
        # Unlocalized but a launch leads the path: trust compiled edges.
        result = (
            pathfind.compiled_edges(app_graph, capability.compiled_path) or []
        )
    elif current is None:
        # Unlocalized with nothing to launch from: fail.
        result = _fail(
            log,
            f'could not localize current screen "{screen.window_title}" '
            f"in graph {app_graph.vendor_id}",
        )
    elif current == capability.goal_node:
        # Already at the goal: nothing to traverse.
        result = []
    else:
        # Elsewhere in the graph: path-find toward the goal.
        found = pathfind.shortest_path(app_graph, current, capability.goal_node)
        if found is None:
            # No route exists: fail.
            result = _fail(
                log,
                f"no path from {current!r} to goal {capability.goal_node!r}",
            )
        else:
            # Route found: replay it.
            log.emit(
                events.PathPlanned(
                    path=[e.id for e in found],
                    start=current,
                    goal=capability.goal_node,
                    summary=f"planned path ({len(found)} edges) from {current}",
                )
            )
            result = found
    return result


def _leading_launch(
    capability: artifact.CapabilityArtifact, app_graph: graph.AppGraph
) -> bool:
    """
    Report whether the compiled path begins with a launch edge.
    """
    launches = False
    if capability.compiled_path:
        try:
            first = app_graph.edge(capability.compiled_path[0])
        except KeyError:
            first = None
        if first is not None:
            launches = first.action.kind == "launch"
    return launches


def _fail(
    log: evidence.EvidenceSink, reason: str, at: str = "(traversal)"
) -> results.ReplayResult:
    """
    Emit a traversal failure and build its failure result.
    """
    log.emit(
        events.ReplayFinished(
            status="failure", summary=f"traversal failed: {reason}"
        )
    )
    result = results.FailureResult(
        failure=results.Failure(
            at_edge=at,
            failure_class="precondition_failed",
            expected="a resolvable path from the current screen to the goal",
            observed=reason,
            evidence_refs=[],
        ),
        evidence_dir=str(log.dir),
    )
    return result
