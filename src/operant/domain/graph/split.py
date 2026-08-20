"""
Split a graph that spans two domains into two graphs.

Given a set of node ids to extract, the extracted nodes and the edges
among them move into a new graph (its own surface binding). In the
original, the extracted nodes are removed and any edge that crossed INTO
the extracted set is rewritten to a single ``invoke`` edge pointing at
the new graph. Immutable versioning means capabilities pinned to the old
version keep working.

Import as:

import operant.domain.graph.split as split
"""

from __future__ import annotations

from typing import List, Optional, Set, Tuple

import operant.domain.models.graph as graph


def _entry_node(app_graph: graph.AppGraph, extract_nodes: Set[str]) -> str:
    """
    Return the extracted node an outside edge points into, else any.
    """
    entries = {
        e.to_node
        for e in app_graph.edges
        if e.from_node not in extract_nodes and e.to_node in extract_nodes
    }
    entry = next(iter(entries), next(iter(extract_nodes)))
    return entry


def _invoke_edge(
    edge: graph.Edge, new_graph_id: str, entry_node: str
) -> graph.Edge:
    """
    Rewrites a crossing edge into an invoke that returns to caller.
    """
    rewritten = edge.model_copy(
        update={
            "to_node": edge.from_node,
            "action": graph.Action(
                kind="invoke",
                graph_ref=graph.GraphRef(
                    graph_id=new_graph_id, target_node=entry_node
                ),
            ),
            "target": None,
            "description": f"invoke {new_graph_id} ({edge.description})",
        }
    )
    return rewritten


def _rewrite_original(
    app_graph: graph.AppGraph,
    extract_nodes: Set[str],
    new_graph_id: str,
    entry_node: str,
) -> graph.AppGraph:
    """
    Drop the extracted set and rewrites crossing edges to invokes.
    """
    kept_nodes = [n for n in app_graph.nodes if n.id not in extract_nodes]
    kept_edges: List[graph.Edge] = []
    for e in app_graph.edges:
        if e.from_node in extract_nodes or e.to_node in extract_nodes:
            # Edge touches the extracted set: rewrite crossings, drop rest.
            if e.from_node not in extract_nodes and e.to_node in extract_nodes:
                kept_edges.append(_invoke_edge(e, new_graph_id, entry_node))
            # Edges fully inside the extracted set leave the original.
        else:
            # Edge lies entirely in the kept graph: carry it over as-is.
            kept_edges.append(e)
    kept_outcomes = [
        o for o in app_graph.outcome_edges if o.at not in extract_nodes
    ]
    rewritten = app_graph.model_copy(
        update={
            "nodes": kept_nodes,
            "edges": kept_edges,
            "outcome_edges": kept_outcomes,
        }
    )
    return rewritten


def _extract_graph(
    app_graph: graph.AppGraph,
    extract_nodes: Set[str],
    new_graph_id: str,
    app_name: str,
    window_title_pattern: str,
) -> graph.AppGraph:
    """
    Build the new graph from the extracted nodes and their edges.
    """
    extracted = graph.AppGraph(
        vendor_id=new_graph_id,
        app_name=app_name,
        window_title_pattern=window_title_pattern,
        nodes=[n for n in app_graph.nodes if n.id in extract_nodes],
        edges=[
            e
            for e in app_graph.edges
            if e.from_node in extract_nodes and e.to_node in extract_nodes
        ],
        outcome_edges=[
            o for o in app_graph.outcome_edges if o.at in extract_nodes
        ],
    )
    return extracted


def split_graph(
    app_graph: graph.AppGraph,
    extract_nodes: Set[str],
    new_graph_id: str,
    *,
    new_app_name: str = "",
    new_window_title_pattern: str = "",
    entry_node: Optional[str] = None,
) -> Tuple[graph.AppGraph, graph.AppGraph]:
    """
    Extract ``extract_nodes`` into a new graph linked by an invoke.

    :param app_graph: The graph to split.
    :param extract_nodes: Ids of the nodes that move to the new graph.
    :param new_graph_id: Vendor id of the new graph.
    :param new_app_name: Surface binding of the new graph; defaults to
        the original's.
    :param new_window_title_pattern: Window regex of the new graph;
        defaults to the original's.
    :param entry_node: Node the invoke edge targets inside the new
        graph; defaults to the extracted node an outside edge points
        into.
    :return:``(rewritten_original, new_graph)``. Neither is persisted
        here.
    :raises ValueError: If any of ``extract_nodes`` is not in the graph.
    """
    missing = extract_nodes - {n.id for n in app_graph.nodes}
    if missing:
        raise ValueError(f"cannot split: nodes not in graph: {sorted(missing)}")
    if not entry_node:
        entry_node = _entry_node(app_graph, extract_nodes)

    new_graph = _extract_graph(
        app_graph,
        extract_nodes,
        new_graph_id,
        new_app_name or app_graph.app_name,
        new_window_title_pattern or app_graph.window_title_pattern,
    )
    rewritten = _rewrite_original(
        app_graph, extract_nodes, new_graph_id, entry_node
    )
    return rewritten, new_graph
