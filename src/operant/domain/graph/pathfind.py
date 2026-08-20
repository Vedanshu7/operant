"""
Deterministic shortest path over the app graph.

BFS by edge count, visited-set for cycles, ties broken by edge id, so
the same (graph, start, goal) always yields the same route. Self-edges
(an action that stays on the same screen, e.g. filling a field) are
followed only when they lie on the way to the goal, never as standalone
hops.

Import as:

import operant.domain.graph.pathfind as pathfind
"""

from __future__ import annotations

import collections
import collections.abc
from typing import Dict, List, Optional

import operant.domain.models.graph as graph


def shortest_path(
    app_graph: graph.AppGraph, start: str, goal: str
) -> Optional[List[graph.Edge]]:
    """
    Find the fewest-edge route from ``start`` to ``goal``.

    :param app_graph: The graph to search.
    :param start: Id of the node to start from.
    :param goal: Id of the node to reach.
    :return: The edges to follow in order; empty when ``start`` is
        ``goal``; ``None`` when ``goal`` is unreachable.
    """
    if start == goal:
        return []
    adjacency: Dict[str, List[graph.Edge]] = {}
    for edge in app_graph.edges:
        adjacency.setdefault(edge.from_node, []).append(edge)
    for edges in adjacency.values():
        edges.sort(key=lambda e: e.id)
    # Explore outward from the start, recording how each node was reached.
    queue: collections.deque[str] = collections.deque([start])
    came_from: Dict[str, graph.Edge] = {}
    visited = {start}
    while queue:
        node = queue.popleft()
        for edge in adjacency.get(node, []):
            nxt = edge.to_node
            if nxt in visited:
                continue
            visited.add(nxt)
            came_from[nxt] = edge
            if nxt == goal:
                return _reconstruct(came_from, start, goal)
            queue.append(nxt)
    return None


def compiled_edges(
    app_graph: graph.AppGraph, edge_ids: collections.abc.Sequence[str]
) -> Optional[List[graph.Edge]]:
    """
    Resolve a cached compiled path of edge ids to edges.

    :param app_graph: The graph the ids refer to.
    :param edge_ids: Ordered edge ids from an artifact's
        ``compiled_path``.
    :return: The edges in order, or ``None`` when any id is missing (the
        graph changed, so the caller re-plans).
    """
    by_id = {e.id: e for e in app_graph.edges}
    out: List[graph.Edge] = []
    for eid in edge_ids:
        edge = by_id.get(eid)
        if edge is None:
            return None
        out.append(edge)
    return out


def _reconstruct(
    came_from: Dict[str, graph.Edge], start: str, goal: str
) -> List[graph.Edge]:
    """
    Walk ``came_from`` back from ``goal`` to ``start``.
    """
    path: List[graph.Edge] = []
    node = goal
    while node != start:
        edge = came_from[node]
        path.append(edge)
        node = edge.from_node
    path.reverse()
    return path
