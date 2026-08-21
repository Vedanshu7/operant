"""
Splitting a multi-app recording at app-switch boundaries.

The entry app's flow stays the caller; each foreign-vendor run becomes
its own ``Recording`` (merged into that vendor's graph by commit), and
the caller's crossing edge is rewritten into an invoke edge that returns
to the caller's screen - the exact shape ``graph.split`` produces and
the traversal layer already replays with retarget. Single-app recordings
pass through untouched.

Import as:

import operant.application.recorder.segment as rssegmen
"""

from __future__ import annotations

import collections.abc
import dataclasses
from typing import List, Tuple

import operant.application.recorder.recording as recdng
import operant.domain.models.graph as graph


def segment_recording(
    recording: recdng.Recording,
) -> Tuple[recdng.Recording, List[recdng.Recording]]:
    """
    Split a recording into the caller's flow plus foreign segments.

    :param recording: The (possibly multi-app) recording.
    :return:``(caller recording, foreign segments)``; the segments list
        is empty for a single-app recording.
    """
    bindings = recording.node_bindings
    primary = bindings.get(
        recording.entry_node,
        (
            recording.vendor_id,
            recording.app_name,
            recording.window_title_pattern,
        ),
    )

    # Resolve each node's binding, defaulting to the primary.
    def binding_of(node_id: str) -> recdng.NodeBinding:
        return bindings.get(node_id, primary)

    segments: List[recdng.Recording] = []
    if all(binding_of(n.id)[0] == primary[0] for n in recording.nodes):
        # Every node shares the primary vendor: nothing to split.
        caller = recording
    else:
        # The run crossed vendors: split off the foreign segments.
        caller_edges, segments = _split_edges(recording, primary, binding_of)
        caller = _caller_recording(recording, primary, caller_edges)
    return caller, segments


def _split_edges(
    recording: recdng.Recording,
    primary: recdng.NodeBinding,
    binding_of: collections.abc.Callable[[str], recdng.NodeBinding],
) -> Tuple[List[graph.Edge], List[recdng.Recording]]:
    """
    Split edges into caller edges and foreign-vendor segments.
    """
    edges = recording.edges
    caller_edges: List[graph.Edge] = []
    segments: List[recdng.Recording] = []
    i = 0
    while i < len(edges):
        edge = edges[i]
        if (
            binding_of(edge.from_node)[0] == primary[0]
            and binding_of(edge.to_node)[0] == primary[0]
        ):
            caller_edges.append(edge)
            i += 1
            continue
        vendor_id = binding_of(edge.to_node)[0]
        seg_edges: List[graph.Edge] = []
        j = i + 1
        while (
            j < len(edges)
            and binding_of(edges[j].from_node)[0] == vendor_id
            and binding_of(edges[j].to_node)[0] == vendor_id
        ):
            seg_edges.append(edges[j])
            j += 1
        segments.append(
            _segment(recording, binding_of(edge.to_node), edge, seg_edges)
        )
        seg_goal = seg_edges[-1].to_node if seg_edges else edge.to_node
        caller_edges.append(_invoke_edge(edge, vendor_id, seg_goal))
        i = j
    return caller_edges, segments


def _segment(
    recording: recdng.Recording,
    binding: recdng.NodeBinding,
    crossing: graph.Edge,
    seg_edges: List[graph.Edge],
) -> recdng.Recording:
    """
    Build a foreign-vendor segment recording.
    """
    vendor_id, app_name, pattern = binding
    node_ids = (
        {crossing.to_node}
        | {e.from_node for e in seg_edges}
        | {e.to_node for e in seg_edges}
    )
    seg_goal = seg_edges[-1].to_node if seg_edges else crossing.to_node
    segment = dataclasses.replace(
        recording,
        capability_id=f"{recording.capability_id}::{vendor_id}",
        vendor_id=vendor_id,
        app_name=app_name,
        window_title_pattern=pattern,
        nodes=[n for n in recording.nodes if n.id in node_ids],
        edges=seg_edges,
        outcome_edges=[o for o in recording.outcome_edges if o.at in node_ids],
        entry_node=crossing.to_node,
        goal_node=seg_goal,
        extract_at_node=seg_goal,
        extract=[],
        node_bindings={},
    )
    return segment


def _invoke_edge(
    crossing: graph.Edge, vendor_id: str, seg_goal: str
) -> graph.Edge:
    """
    Rewrite the crossing edge into an invoke edge.
    """
    edge = crossing.model_copy(
        update={
            "to_node": crossing.from_node,
            "action": graph.Action(
                kind="invoke",
                graph_ref=graph.GraphRef(
                    graph_id=vendor_id, target_node=seg_goal
                ),
            ),
            "target": None,
            "description": f"invoke {vendor_id} ({crossing.description})",
        }
    )
    return edge


def _caller_recording(
    recording: recdng.Recording,
    primary: recdng.NodeBinding,
    caller_edges: List[graph.Edge],
) -> recdng.Recording:
    """
    Build the caller's flow recording from the retained edges.
    """
    bindings = recording.node_bindings
    node_ids = (
        {recording.entry_node}
        | {e.from_node for e in caller_edges}
        | {e.to_node for e in caller_edges}
    )
    caller_goal = (
        caller_edges[-1].to_node if caller_edges else recording.entry_node
    )
    caller = dataclasses.replace(
        recording,
        vendor_id=primary[0],
        app_name=primary[1],
        window_title_pattern=primary[2],
        nodes=[n for n in recording.nodes if n.id in node_ids],
        edges=caller_edges,
        outcome_edges=[
            o for o in recording.outcome_edges if o.at == "*" or o.at in node_ids
        ],
        goal_node=caller_goal,
        extract_at_node=(
            recording.extract_at_node
            if recording.extract_at_node in node_ids
            else caller_goal
        ),
        policy_scope=recording.policy_scope.model_copy(
            update={
                "required_action_kinds": sorted(
                    {e.action.kind for e in caller_edges}
                ),
            }
        ),
        node_bindings={nid: b for nid, b in bindings.items() if nid in node_ids},
    )
    return caller
