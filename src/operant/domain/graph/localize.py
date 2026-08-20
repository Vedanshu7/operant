"""
Localize the live screen within the app graph: which node am I on?

Pure over (ScreenDigest, AppGraph). This is what makes start-from-the-
middle work: observe the current state, find its node, then path-find to
the goal.

Content-addressed: when nodes carry a value-free content fingerprint
(2.3+ graphs) we match by how much of a node's fingerprint is present on
the live screen, because titles and URLs repeat across states (a bank's
index page keeps its title logged in or out) while the content does not.
Pre-2.3 graphs, whose nodes have no fingerprint, fall back to the
title/text/element checks unchanged.

Import as:

import operant.domain.graph.localize as localize
"""

from __future__ import annotations

import collections.abc
from typing import Dict, List, Optional, Tuple

import operant.domain.fingerprint as odfinger
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import operant.domain.outcomes as outcomes
import operant.domain.params as params

_MIN_COVERAGE = 0.6
_MIN_PRESENT = 2


def locate(
    screen: digest.ScreenDigest,
    app_graph: graph.AppGraph,
    inputs: Optional[collections.abc.Mapping[str, str]] = None,
) -> Optional[str]:
    """
    Find the node the live screen is on.

    Prefers content-fingerprint coverage; falls back to node checks when
    no node has a fingerprint (older graphs) or none match by content.

    :param screen: The current screen digest.
    :param app_graph: The graph to search.
    :param inputs: Task inputs substituted into parameterised checks.
    :return: The matching node id, or ``None`` when nothing matches.
    """
    values = dict(inputs or {})
    node_id: Optional[str] = None
    if any(node.fingerprint for node in app_graph.nodes):
        node_id = _by_fingerprint(app_graph.nodes, screen, values)
    if node_id is None:
        node_id = _by_checks(app_graph.nodes, screen, values)
    return node_id


def _by_fingerprint(
    nodes: collections.abc.Sequence[graph.Node],
    screen: digest.ScreenDigest,
    values: Dict[str, str],
) -> Optional[str]:
    screen_fp = set(odfinger.of(screen))
    scored: List[Tuple[float, bool, str]] = []
    for node in nodes:
        if not node.fingerprint:
            continue
        cover = odfinger.coverage(node.fingerprint, screen_fp)
        present = sum(1 for sig in node.fingerprint if sig in screen_fp)
        if cover >= _MIN_COVERAGE and present >= _MIN_PRESENT:
            checks = [params.substitute_condition(c, values) for c in node.checks]
            scored.append((cover, outcomes.on_node(checks, screen), node.id))
    scored.sort(key=lambda s: (-s[0], not s[1], s[2]))
    best = scored[0][2] if scored else None
    return best


def _by_checks(
    nodes: collections.abc.Sequence[graph.Node],
    screen: digest.ScreenDigest,
    values: Dict[str, str],
) -> Optional[str]:
    matches: List[Tuple[int, str]] = []
    for node in nodes:
        checks = [params.substitute_condition(c, values) for c in node.checks]
        if outcomes.on_node(checks, screen):
            matches.append((len(node.checks), node.id))
    matches.sort(key=lambda m: (-m[0], m[1]))
    best = matches[0][1] if matches else None
    return best
