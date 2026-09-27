"""
Committing a recording: graph merge plus the path-query capability.

This is the seam where a recording becomes (a) shared graph structure
and (b) a lightweight capability that names start/goal and caches the
compiled path for deterministic replay. A recording that crossed apps is
segmented first: each foreign-vendor run merges into ITS vendor's graph,
and the caller keeps an invoke edge in their place.

Import as:

import operant.application.capabilities as capab
"""

from __future__ import annotations

import collections.abc
import dataclasses
from typing import Dict, List, Optional, Tuple

import operant.application.recorder.recording as recdng
import operant.application.recorder.segment as rssegmen
import operant.domain.errors as errors
import operant.domain.graph.merge as merge
import operant.domain.graph.review as review
import operant.domain.models.artifact as artifact
import operant.domain.models.graph as graph
import operant.domain.models.runs as runs
import operant.domain.models.targets as targets
import operant.helpers.time as time
import operant.ports.repositories as prepos

# Actions that act on a control, as opposed to launch, press or scroll.
_TARGETED = frozenset({"click", "fill", "select"})
# Strategies that find a control by what it is called.
_NAMED_STRATEGIES = (targets.RoleStrategy, targets.LabelProximityStrategy)


def commit_recording(
    recording: recdng.Recording,
    *,
    graph_store: prepos.GraphRepository,
    artifact_store: prepos.ArtifactRepository,
    retire: collections.abc.Set[str] = frozenset(),
) -> Tuple[artifact.CapabilityArtifact, graph.AppGraph]:
    """
    Merge a recording into its graph(s) and saves the capability.

    :param recording: the recording to commit.
    :param graph_store: versioned graph storage.
    :param artifact_store: versioned artifact storage.
    :param retire: failing edges a rediscovery may replace.
    :return: ``(saved capability, the graph version it pins)``.
    """
    caller, callees = rssegmen.segment_recording(recording)
    callee_node_remaps: Dict[str, Dict[str, str]] = {}
    for segment in callees:
        _, node_remap, _ = _merge_segment(segment, graph_store)
        callee_node_remaps[segment.vendor_id] = node_remap
    if callee_node_remaps:
        caller = dataclasses.replace(
            caller,
            edges=[_remap_invoke(e, callee_node_remaps) for e in caller.edges],
        )
    merged, node_remap, edge_remap = _merge_segment(caller, graph_store, retire)

    # Build the capability, remapping its ids into the merged graph.
    def mapped(node_id: str) -> str:
        """
        Return the id a node has in the merged graph.
        """
        return node_remap.get(node_id, node_id)

    capability = artifact.CapabilityArtifact(
        id=caller.capability_id,
        name=caller.capability_name,
        description=caller.goal,
        vendor_id=caller.vendor_id,
        graph_version=merged.graph_version,
        tenants=caller.tenants,
        default_tenant=caller.default_tenant,
        inputs=caller.inputs,
        outputs=caller.outputs,
        start_node=mapped(caller.entry_node),
        goal_node=mapped(caller.goal_node),
        extract_at_node=mapped(caller.extract_at_node),
        extract=caller.extract,
        compiled_path=[edge_remap.get(e.id, e.id) for e in caller.edges],
        policy_scope=caller.policy_scope,
        provenance=artifact.Provenance(**caller.provenance.model_dump()),
        accessibility=accessibility_of(caller.edges),
    )
    saved = artifact_store.save_new_version(capability)
    return saved, merged


def _repin_problems(
    capability: artifact.CapabilityArtifact,
    target: graph.AppGraph,
    graph_store: prepos.GraphRepository,
) -> List[str]:
    """
    Name what stops a capability's path from running on ``target``.
    """
    nodes = {node.id for node in target.nodes}
    edges = {edge.id: edge for edge in target.edges}
    wanted = [
        ("goal node", capability.goal_node),
        (
            "start node",
            "" if capability.start_node == "*" else capability.start_node,
        ),
        ("extraction node", capability.extract_at_node or ""),
    ]
    problems = [
        f"{what} {node} is gone"
        for what, node in wanted
        if node and node not in nodes
    ]
    previous: Optional[graph.Edge] = None
    for edge_id in capability.compiled_path:
        edge = edges.get(edge_id)
        if edge is None:
            problems.append(f"edge {edge_id} is gone")
        elif edge.retired_in is not None:
            problems.append(f"edge {edge_id} is retired")
        else:
            if previous is not None and previous.to_node != edge.from_node:
                problems.append(f"edge {edge_id} no longer follows {previous.id}")
            problems.extend(_invoke_problems(edge, graph_store))
        previous = edge
    return problems


def _invoke_problems(
    edge: graph.Edge, graph_store: prepos.GraphRepository
) -> List[str]:
    """
    Name what stops an invoke edge from reaching its callee.
    """
    ref = edge.action.graph_ref
    problems: List[str] = []
    if ref is not None:
        if not graph_store.exists(ref.graph_id):
            problems.append(f"edge {edge.id} invokes missing {ref.graph_id}")
        elif ref.target_node is not None:
            callee = graph_store.get(ref.graph_id, ref.version)
            if ref.target_node not in {node.id for node in callee.nodes}:
                problems.append(
                    f"edge {edge.id} target {ref.target_node} is gone"
                )
    return problems


def repin(
    capability: artifact.CapabilityArtifact,
    *,
    graph_store: prepos.GraphRepository,
    artifact_store: prepos.ArtifactRepository,
    run_repo: prepos.RunRepository,
    by: str,
    version: Optional[int] = None,
) -> artifact.CapabilityArtifact:
    """
    Move a capability to another graph version, as a draft.

    A different graph is a different thing to trust, so a person
    approves it again and its earlier replays stop counting.

    :param capability: the capability to move.
    :param graph_store: versioned graph storage.
    :param artifact_store: versioned artifact storage.
    :param run_repo: where the track record and audit trail live.
    :param by: who asked.
    :param version: the target; the newest when ``None``.
    :return: the new artifact version, or ``capability`` if already
        there.
    :raises errors.RepinRefusedError: if its path is not on that
        version.
    """
    target = graph_store.get(capability.vendor_id, version)
    if target.graph_version == capability.graph_version:
        return capability
    problems = _repin_problems(capability, target, graph_store)
    if problems:
        raise errors.RepinRefusedError(
            f"{capability.id} cannot move to graph v{target.graph_version}: "
            f"{'; '.join(problems)}. Rebuild it with discover --seed {capability.id}"
        )
    run_repo.close_samples(capability.id)
    moved = artifact_store.save_new_version(
        capability.model_copy(
            update={"graph_version": target.graph_version, "status": "draft"}
        )
    )
    run_repo.audit(
        runs.AuditEntry(
            at=time.iso_now(),
            actor=by,
            action="repin_artifact",
            subject=capability.id,
            detail={
                "from": str(capability.graph_version),
                "to": str(target.graph_version),
            },
        )
    )
    return moved


def outstanding_steps(
    capability: artifact.CapabilityArtifact,
    graph_store: prepos.GraphRepository,
    edge_records: prepos.EdgeRecordRepository,
) -> List[graph.Edge]:
    """
    Return the unknown steps a person must see before approving.

    :param capability: the capability.
    :param graph_store: versioned graph storage.
    :param edge_records: where reviews are kept.
    :return: the steps not reviewed on its pinned graph.
    """
    pinned = graph_store.get(capability.vendor_id, capability.graph_version)
    return review.outstanding_steps(
        pinned,
        capability.compiled_path,
        lambda key: edge_records.is_approved(
            capability.vendor_id, capability.graph_version, key
        ),
    )


def review_unknown_steps(
    capability: artifact.CapabilityArtifact,
    graph_store: prepos.GraphRepository,
    edge_records: prepos.EdgeRecordRepository,
    *,
    by: str,
) -> List[graph.Edge]:
    """
    Record a person's approval as the review of a capability's unknown steps.

    :param capability: the capability being approved.
    :param graph_store: versioned graph storage.
    :param edge_records: where reviews are kept.
    :param by: who approved.
    :return: the steps reviewed, for showing to that person.
    """
    pinned = graph_store.get(capability.vendor_id, capability.graph_version)
    steps = review.unknown_steps(pinned, capability.compiled_path)
    edge_records.approve(
        capability.vendor_id,
        capability.graph_version,
        [review.review_key(step) for step in steps],
        by=by,
    )
    return steps


def _merge_segment(
    recording: recdng.Recording,
    graph_store: prepos.GraphRepository,
    retire: collections.abc.Set[str] = frozenset(),
) -> Tuple[graph.AppGraph, Dict[str, str], Dict[str, str]]:
    """
    Merge one recording into its vendor's graph; skips a no-op write.
    """
    base = (
        graph_store.get(recording.vendor_id)
        if graph_store.exists(recording.vendor_id)
        else None
    )
    merged, changed, node_remap, edge_remap = merge.merge_recording(
        base,
        recording.vendor_id,
        recording.nodes,
        recording.edges,
        recording.outcome_edges,
        app_name=recording.app_name,
        window_title_pattern=recording.window_title_pattern,
        retire=retire,
    )
    if base is None or changed:
        # First write or genuinely changed: persist a new version.
        merged = graph_store.save_new_version(merged)
    else:
        # Nothing changed: keep the existing version.
        merged = base
    return merged, node_remap, edge_remap


def _remap_invoke(
    edge: graph.Edge, remaps: Dict[str, Dict[str, str]]
) -> graph.Edge:
    """
    Rewrite an invoke edge's target node to its merged graph id.
    """
    ref = edge.action.graph_ref
    remapped = edge
    if (
        edge.action.kind == "invoke"
        and ref is not None
        and ref.graph_id in remaps
    ):
        remap = remaps[ref.graph_id]
        if ref.target_node in remap:
            remapped = edge.model_copy(
                update={
                    "action": edge.action.model_copy(
                        update={
                            "graph_ref": ref.model_copy(
                                update={"target_node": remap[ref.target_node]}
                            ),
                        }
                    ),
                }
            )
    return remapped


def accessibility_of(
    edges: collections.abc.Sequence[graph.Edge],
) -> artifact.Accessibility:
    """
    Count how the recorded steps locate their targets.

    :param edges: the recorded steps.
    :return: targeted steps, and how many rely on position or path only.
    """
    targeted = [e for e in edges if e.action.kind in _TARGETED]
    coordinate = unnamed = 0
    for edge in targeted:
        strategies = edge.target.strategies if edge.target is not None else []
        if all(_is_region(s) for s in strategies):
            # No target, or only a recorded screen point.
            coordinate += 1
        elif not any(isinstance(s, _NAMED_STRATEGIES) for s in strategies):
            unnamed += 1
    return artifact.Accessibility(
        steps=len(targeted), coordinate_steps=coordinate, unnamed_steps=unnamed
    )


def _is_region(strategy: targets.TargetStrategy) -> bool:
    """
    Report whether a strategy is only a recorded screen point.
    """
    region = (
        isinstance(strategy, targets.RegionStrategy)
        and strategy.role == recdng.REGION_ROLE
    )
    return region
