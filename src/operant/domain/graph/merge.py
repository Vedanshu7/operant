"""
Merge a recorded flow into the application graph.

Node identity is the primary ``titleMatches`` pattern plus content: a
recorded screen with an existing node's title and enough of its fingerprint
IS that node, while two states that only share a title stay apart. This is
how login and navigation become shared subgraphs reused across capabilities
instead of being re-recorded. Edges dedupe by (from, to, action signature); outcome
edges by id. Any change yields a new immutable graph version.

``merge_recording`` takes the recording's nodes, edges, and outcome
edges as explicit sequences rather than a recorder ``Recording`` object,
so this module depends on the graph models only.

Import as:

import operant.domain.graph.merge as merge
"""

from __future__ import annotations

import collections.abc
from typing import Dict, List, Optional, Set, Tuple

import operant.domain.fingerprint as odfinger
import operant.domain.models.graph as graph


def _node_key(node: graph.Node) -> str:
    """
    Screen identity: the first title pattern, else every check.
    """
    key = None
    for check in node.checks:
        if isinstance(check, graph.TitleMatches):
            key = f"title:{check.pattern}"
            break
    if key is None:
        key = "checks:" + "|".join(
            f"{c.kind}:{getattr(c, 'pattern', '')}" for c in node.checks
        )
    return key


def _target_sig(edge: graph.Edge) -> str:
    """
    Identity of the control an edge acts on.

    Two clicks on different controls of the SAME screen (username field
    vs password field vs a button) are distinct edges, not collapsed
    into one by dedup.
    """
    sig = ""
    if edge.target is not None and edge.target.strategies:
        s = edge.target.strategies[0]
        sig = (
            getattr(s, "name", None)
            or getattr(s, "anchor_text", None)
            or getattr(s, "path", "")
            or ""
        )
    return sig


def _unique(base: str, taken: Set[str]) -> str:
    """
    Return ``base`` or the first ``base-N`` not in ``taken``.
    """
    result = base
    if base in taken:
        n = 2
        while f"{base}-{n}" in taken:
            n += 1
        result = f"{base}-{n}"
    return result


def _edge_key(edge: graph.Edge) -> str:
    """
    Dedup key: endpoints, action kind, payload, graph ref, target.
    """
    action = edge.action
    value = ""
    if action.value is not None:
        value = (
            action.value.param
            or action.value.secret_ref
            or action.value.from_output
            or (action.value.literal or "")
        )
    ref = action.graph_ref.graph_id if action.graph_ref else ""
    key = (
        f"{edge.from_node}->{edge.to_node}:{action.kind}"
        f":{action.url or action.key or ''}"
        f":{value}:{ref}:{_target_sig(edge)}"
    )
    return key


def _same_state(
    existing: graph.Node,
    node: graph.Node,
    existing_edges: collections.abc.Sequence[graph.Edge],
    edges: collections.abc.Sequence[graph.Edge],
) -> bool:
    """
    Report whether a recorded node is an existing node with the same title.

    With a fingerprint on both sides, content decides. A node with none
    takes a fingerprint only if the recording leaves it the same way: a
    logged-in home page must not write its content onto the logged-out one.
    """
    if existing.fingerprint and node.fingerprint:
        cover = odfinger.coverage(existing.fingerprint, set(node.fingerprint))
        same = cover >= odfinger.SAME_SCREEN_COVERAGE
    elif node.fingerprint:
        known = {
            _target_sig(e) for e in existing_edges if e.from_node == existing.id
        }
        recorded = {_target_sig(e) for e in edges if e.from_node == node.id}
        same = not known or not recorded or bool(known & recorded)
    else:
        same = True
    return same


def _merge_nodes(
    existing_nodes: List[graph.Node],
    nodes: collections.abc.Sequence[graph.Node],
    existing_edges: collections.abc.Sequence[graph.Edge] = (),
    edges: collections.abc.Sequence[graph.Edge] = (),
) -> Tuple[Dict[str, str], bool]:
    """
    Append unseen nodes in place; returns (node remap, changed).
    """
    node_ids = {n.id for n in existing_nodes}
    node_remap: Dict[str, str] = {}
    changed = False
    for node in nodes:
        key = _node_key(node)
        existing = next(
            (
                n
                for n in existing_nodes
                if _node_key(n) == key
                and _same_state(n, node, existing_edges, edges)
            ),
            None,
        )
        if existing is not None:
            # Reuse the shared node (e.g. the login screen), adding what an
            # older recording of it did not capture.
            node_remap[node.id] = existing.id
            upgraded = existing.model_copy(
                update={
                    "fingerprint": existing.fingerprint or node.fingerprint,
                    "url_paths": sorted({*existing.url_paths, *node.url_paths}),
                }
            )
            if upgraded != existing:
                existing_nodes[existing_nodes.index(existing)] = upgraded
                changed = True
        else:
            # Recording-local ids can collide with ids already in the
            # graph (every recording counts from 1): unique-ify first.
            new_id = _unique(node.id, node_ids)
            stored = (
                node
                if new_id == node.id
                else node.model_copy(update={"id": new_id})
            )
            existing_nodes.append(stored)
            node_ids.add(new_id)
            node_remap[node.id] = new_id
            changed = True
    return node_remap, changed


def _merge_edges(
    existing_edges: List[graph.Edge],
    edges: collections.abc.Sequence[graph.Edge],
    node_remap: Dict[str, str],
) -> Tuple[Dict[str, str], bool]:
    """
    Append unseen edges in place; returns (edge remap, changed).
    """
    edges_by_key = {_edge_key(e): e for e in existing_edges}
    edge_ids = {e.id for e in existing_edges}
    edge_remap: Dict[str, str] = {}
    changed = False
    for edge in edges:
        moved = edge.model_copy(
            update={
                "from_node": node_remap.get(edge.from_node, edge.from_node),
                "to_node": node_remap.get(edge.to_node, edge.to_node),
            }
        )
        key = _edge_key(moved)
        existing = edges_by_key.get(key)
        if existing is not None:
            # An identical edge is already here: point at it, add nothing.
            edge_remap[edge.id] = existing.id
        else:
            # A genuinely new edge: unique-ify a colliding id and append.
            new_id = _unique(moved.id, edge_ids)
            if new_id != moved.id:
                moved = moved.model_copy(update={"id": new_id})
            existing_edges.append(moved)
            edges_by_key[key] = moved
            edge_ids.add(new_id)
            edge_remap[edge.id] = new_id
            changed = True
    return edge_remap, changed


def _retire_edges(
    existing_edges: List[graph.Edge],
    retire: collections.abc.Set[str],
    *,
    recorded: collections.abc.Set[str],
    next_version: int,
) -> bool:
    """
    Retire failing edges the recording replaced, in place; returns changed.
    """
    reached = {e.to_node for e in existing_edges if e.id in recorded}
    changed = False
    for index, edge in enumerate(existing_edges):
        if (
            edge.id in retire
            and edge.id not in recorded
            and edge.to_node in reached
            and edge.retired_in is None
        ):
            existing_edges[index] = edge.model_copy(
                update={"retired_in": next_version}
            )
            changed = True
    return changed


def _merge_outcomes(
    existing_outcomes: List[graph.OutcomeEdge],
    outcome_edges: collections.abc.Sequence[graph.OutcomeEdge],
    node_remap: Dict[str, str],
) -> bool:
    """
    Append outcome edges with unseen ids in place; returns changed.
    """
    outcome_ids = {o.id for o in existing_outcomes}
    changed = False
    for outcome in outcome_edges:
        at = node_remap.get(outcome.at, outcome.at) if outcome.at != "*" else "*"
        moved = outcome.model_copy(update={"at": at})
        if moved.id not in outcome_ids:
            existing_outcomes.append(moved)
            outcome_ids.add(moved.id)
            changed = True
    return changed


def merge_recording(
    base: Optional[graph.AppGraph],
    vendor_id: str,
    nodes: collections.abc.Sequence[graph.Node],
    edges: collections.abc.Sequence[graph.Edge],
    outcome_edges: collections.abc.Sequence[graph.OutcomeEdge],
    *,
    app_name: str = "",
    window_title_pattern: str = "",
    retire: collections.abc.Set[str] = frozenset(),
) -> Tuple[graph.AppGraph, bool, Dict[str, str], Dict[str, str]]:
    """
    Fold a recorded flow into ``base`` (or a fresh graph).

    :param base: the current graph version, or ``None`` for a first
        save.
    :param vendor_id: application the graph belongs to.
    :param nodes: screen nodes the recording observed.
    :param edges: actions the recording took between those nodes.
    :param outcome_edges: detectors the recording declared.
    :param app_name: surface binding; keeps ``base``'s when empty.
    :param window_title_pattern: window regex; keeps ``base``'s when
        empty.
    :param retire: edge ids known to keep failing; one retires only if
        this recording reached its destination another way.
    :return: ``(graph, changed, node_remap, edge_remap)``. The remaps map
        the recording's node/edge ids to the graph's canonical ids (e.g.
        a reused login subgraph) so the caller can point a capability's
        start/goal and compiled path at them. The graph keeps ``base``'s
        version number; the caller bumps it when ``changed`` is true.
    """
    existing_nodes = list(base.nodes) if base else []
    existing_edges = list(base.edges) if base else []
    existing_outcomes = list(base.outcome_edges) if base else []
    # Fold each kind of element into the existing contents in place.
    node_remap, nodes_changed = _merge_nodes(
        existing_nodes, nodes, existing_edges, edges
    )
    edge_remap, edges_changed = _merge_edges(existing_edges, edges, node_remap)
    outcomes_changed = _merge_outcomes(
        existing_outcomes, outcome_edges, node_remap
    )
    retired = _retire_edges(
        existing_edges,
        retire,
        recorded=set(edge_remap.values()),
        next_version=(base.graph_version if base else 0) + 1,
    )
    changed = nodes_changed or edges_changed or outcomes_changed or retired
    contents = (existing_nodes, existing_edges, existing_outcomes)
    merged = _assemble(base, vendor_id, app_name, window_title_pattern, contents)
    return merged, changed, node_remap, edge_remap


def _assemble(
    base: Optional[graph.AppGraph],
    vendor_id: str,
    app_name: str,
    window_title_pattern: str,
    contents: Tuple[List[graph.Node], List[graph.Edge], List[graph.OutcomeEdge]],
) -> graph.AppGraph:
    """
    Build the merged graph, inheriting ``base``'s metadata.
    """
    nodes, edges, outcome_edges = contents
    merged = graph.AppGraph(
        vendor_id=vendor_id,
        graph_version=base.graph_version if base else 1,
        app_name=app_name or (base.app_name if base else ""),
        window_title_pattern=window_title_pattern
        or (base.window_title_pattern if base else ""),
        nodes=nodes,
        edges=edges,
        outcome_edges=outcome_edges,
        created_at=base.created_at if base else "",
    )
    return merged
