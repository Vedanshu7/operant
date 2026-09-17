"""
Noticing a UI change, and learning a screen's stable core across visits.

Checks say a run arrived; the two fingerprint views say whether the screen
still looks the way it was recorded. A verified arrival that lost a view
means the UI moved under a working capability, which is worth a person's
attention before the capability breaks.

Learning never happens during a run: one banner must not become part of a
screen's identity, so a core is the intersection of several verified visits,
saved as a new graph version on command.

Import as:

import operant.domain.graph.drift as ogdrift
"""

from __future__ import annotations

import collections
import collections.abc
from typing import Dict, Final, List, Optional

import operant.domain.errors as errors
import operant.domain.fingerprint as odfinger
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph

# Verified visits needed before a stable core replaces a fingerprint.
MIN_VISITS: Final = 3
# Verified visits considered per node, newest first.
MAX_VISITS: Final = 10


def lost_views(node: graph.Node, screen: digest.ScreenDigest) -> List[str]:
    """
    Name the fingerprint views the screen no longer covers.

    :param node: the node the run arrived at.
    :param screen: the screen it arrived on.
    :return: ``text`` and/or ``structure``; empty when both hold, or when
        the node has no fingerprint to compare.
    """
    if not node.fingerprint:
        return []
    recorded = odfinger.views(node.fingerprint)
    live = odfinger.views(odfinger.of(screen))
    lost = []
    if (
        odfinger.coverage(sorted(recorded.text), live.text)
        < odfinger.SAME_SCREEN_COVERAGE
    ):
        lost.append("text")
    if (
        odfinger.coverage(sorted(recorded.structure), live.structure)
        < odfinger.SAME_SCREEN_COVERAGE
    ):
        lost.append("structure")
    return lost


def recent_visits(
    visits: collections.abc.Sequence[collections.abc.Sequence[str]],
) -> List[List[str]]:
    """
    Keep the visits that show the same look as the newest one.

    A redesign must not be intersected with the old page: that would leave
    only the shared menu. Walking back stops where the look changes.

    :param visits: fingerprints, oldest first.
    :return: the matching run of recent visits, oldest first, at most
        ``MAX_VISITS``.
    """
    if not visits:
        return []
    newest = visits[-1]
    kept: List[List[str]] = []
    for visit in reversed(visits[-MAX_VISITS:]):
        cover = odfinger.coverage(list(visit), set(newest))
        if cover < odfinger.SAME_SCREEN_COVERAGE:
            break
        kept.append(list(visit))
    kept.reverse()
    return kept


def stable_core(
    visits: collections.abc.Sequence[collections.abc.Sequence[str]],
) -> Optional[List[str]]:
    """
    Return the signatures present on every visit.

    :param visits: the fingerprint of each verified visit.
    :return: the sorted core; ``None`` with too few visits or an empty
        core.
    """
    if len(visits) < MIN_VISITS:
        return None
    core = set(visits[0]).intersection(*(set(v) for v in visits[1:]))
    return sorted(core) or None


def retire(
    app_graph: graph.AppGraph, edge_ids: collections.abc.Set[str]
) -> graph.AppGraph:
    """
    Build the next graph with these edges retired.

    :param app_graph: the current graph.
    :param edge_ids: the edges to retire.
    :return: the changed graph.
    :raises errors.NotFoundError: if an edge is not in the graph.
    """
    edges = {edge.id for edge in app_graph.edges}
    missing = sorted(edge_ids - edges)
    if missing:
        raise errors.NotFoundError(f"Unknown edges: {', '.join(missing)}")
    next_version = app_graph.graph_version + 1
    updated = [
        (
            edge.model_copy(update={"retired_in": next_version})
            if edge.id in edge_ids and edge.retired_in is None
            else edge
        )
        for edge in app_graph.edges
    ]
    return app_graph.model_copy(update={"edges": updated})


def relearn(
    app_graph: graph.AppGraph,
    visits: collections.abc.Mapping[str, collections.abc.Sequence[List[str]]],
    url_paths: collections.abc.Mapping[str, collections.abc.Sequence[str]],
) -> Optional[graph.AppGraph]:
    """
    Build the next graph from verified visits, when that changes anything.

    :param app_graph: the graph the visits ran on.
    :param visits: fingerprints seen per node id, oldest first.
    :param url_paths: the normalised address of each visit per node id;
        an address needs ``MIN_VISITS`` visits too.
    :return: the changed graph, or ``None`` when nothing changed.
    """
    changed: Dict[str, graph.Node] = {}
    for node in app_graph.nodes:
        core = stable_core(recent_visits(visits.get(node.id, ())))
        seen = collections.Counter(url_paths.get(node.id, ()))
        steady = {path for path, count in seen.items() if count >= MIN_VISITS}
        paths = sorted({*node.url_paths, *steady})
        updated = node.model_copy(
            update={"fingerprint": core or node.fingerprint, "url_paths": paths}
        )
        if updated != node:
            changed[node.id] = updated
    if not changed:
        return None
    nodes = [changed.get(node.id, node) for node in app_graph.nodes]
    return app_graph.model_copy(update={"nodes": nodes})
