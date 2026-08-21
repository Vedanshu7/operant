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

import dataclasses
from typing import Dict, Tuple

import operant.application.recorder.recording as recdng
import operant.application.recorder.segment as rssegmen
import operant.domain.graph.merge as merge
import operant.domain.models.artifact as artifact
import operant.domain.models.graph as graph
import operant.infra.repositories.artifacts as raartifa
import operant.infra.repositories.graphs as graphs


def commit_recording(
    recording: recdng.Recording,
    *,
    graph_store: graphs.FileGraphRepository,
    artifact_store: raartifa.FileArtifactRepository,
) -> Tuple[artifact.CapabilityArtifact, graph.AppGraph]:
    """
    Merge a recording into its graph(s) and saves the capability.

    :param recording: The recording to commit.
    :param graph_store: Versioned graph storage.
    :param artifact_store: Versioned artifact storage.
    :return:``(saved capability, the graph version it pins)``.
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
    merged, node_remap, edge_remap = _merge_segment(caller, graph_store)

    # Build the capability, remapping its ids into the merged graph.
    def mapped(node_id: str) -> str:
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
    )
    saved = artifact_store.save_new_version(capability)
    return saved, merged


def _merge_segment(
    recording: recdng.Recording,
    graph_store: graphs.FileGraphRepository,
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
    Rewrites an invoke edge's target node to its merged graph id.
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
