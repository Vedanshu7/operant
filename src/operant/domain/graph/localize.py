"""
Localize the live screen within the app graph: which node am I on?

Pure over (ScreenDigest, AppGraph). This is what makes start-from-the-
middle work: observe the current state, find its node, then path-find to
the goal.

A best score alone is not an answer, so ``locate`` says how sure it is:

- ``match``: one node fits, its checks hold, and the URL does not disagree.
- ``drifted``: one node fits, but something disagrees. Either the content
  matches while the checks or URL do not (a page that only looks like it),
  or the checks hold while the content no longer matches (the UI changed).
- ``ambiguous``: more than one node fits.
- ``unknown``: nothing fits.

Identity comes from what is unique to a node, in two views (see
``fingerprint.ScreenViews``), so one kind of UI change cannot erase it. It
needs every live node to carry a fingerprint, because uniqueness means nothing
on a partly recorded graph. Whole-fingerprint coverage comes next, then the node
checks.

Import as:

import operant.domain.graph.localize as localize
"""

from __future__ import annotations

import collections.abc
import dataclasses
from typing import Dict, Final, List, Literal, Optional, Tuple

import operant.domain.fingerprint as odfinger
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import operant.domain.outcomes as outcomes
import operant.domain.params as params

Kind = Literal["match", "drifted", "ambiguous", "unknown"]

_MIN_PRESENT: Final = 2


# #############################################################################
# Localization
# #############################################################################


@dataclasses.dataclass(frozen=True)
class Localization:
    """
    Where the live screen is, and how sure that is.

    :ivar kind: ``match``, ``drifted``, ``ambiguous`` or ``unknown``.
    :ivar node_id: the node, for ``match`` and ``drifted``.
    :ivar candidates: the nodes that tied, for ``ambiguous``.
    :ivar basis: what decided: ``identity``, ``coverage`` or ``checks``.
    """

    kind: Kind
    node_id: Optional[str] = None
    candidates: Tuple[str, ...] = ()
    basis: str = ""

    @property
    def confirmed(self) -> Optional[str]:
        """
        The node, only when it is a clean match.
        """
        return self.node_id if self.kind == "match" else None


def locate(
    screen: digest.ScreenDigest,
    app_graph: graph.AppGraph,
    inputs: Optional[collections.abc.Mapping[str, str]] = None,
    *,
    expected: Optional[str] = None,
) -> Localization:
    """
    Find the node the live screen is on.

    :param screen: the current screen digest.
    :param app_graph: the graph to search.
    :param inputs: task inputs substituted into parameterised checks.
    :param expected: the node the path predicts; it settles a tie
        between candidates and nothing else.
    :return: the node, and how sure that is.
    """
    values = dict(inputs or {})
    nodes = app_graph.nodes
    judged = _live_nodes(app_graph)
    complete = len(judged) > 1 and all(node.fingerprint for node in judged)
    found = _by_identity(judged, screen, values, expected) if complete else None
    if found is None:
        # A node whose controls all appear on a bigger screen has no identity.
        found = _by_coverage(nodes, screen, values)
    if found is None:
        found = _by_checks(nodes, screen, values, expected, drifted=complete)
    return found


def _live_nodes(app_graph: graph.AppGraph) -> List[graph.Node]:
    """
    Return the nodes identity has to separate.

    A node with no fingerprint and no live edge is left behind by retired
    steps: nothing can reach it, so it must not hold identity back.
    """
    touched = {
        node_id
        for edge in app_graph.edges
        if edge.retired_in is None
        for node_id in (edge.from_node, edge.to_node)
    }
    live = [
        node for node in app_graph.nodes if node.fingerprint or node.id in touched
    ]
    return live


def _holds(
    node: graph.Node, screen: digest.ScreenDigest, values: Dict[str, str]
) -> bool:
    """
    Report whether a node's checks pass on the screen.
    """
    checks = [params.substitute_condition(c, values) for c in node.checks]
    held = outcomes.on_node(checks, screen)
    return held


def _url_disagrees(node: graph.Node, screen: digest.ScreenDigest) -> bool:
    """
    Report whether the live address rules this node out.
    """
    live = odfinger.url_path(screen.url)
    disagrees = bool(live and node.url_paths and live not in node.url_paths)
    return disagrees


def _settled(
    node: graph.Node,
    screen: digest.ScreenDigest,
    values: Dict[str, str],
    basis: str,
) -> Localization:
    """
    Turn one winning node into a ``match`` or ``drifted`` result.
    """
    clean = _holds(node, screen, values) and not _url_disagrees(node, screen)
    return Localization("match" if clean else "drifted", node.id, basis=basis)


def _unique_views(
    nodes: collections.abc.Sequence[graph.Node],
) -> Dict[str, odfinger.ScreenViews]:
    """
    Return, per node, the signatures no other node has, in each view.
    """
    every = {node.id: odfinger.views(node.fingerprint) for node in nodes}
    unique: Dict[str, odfinger.ScreenViews] = {}
    for node_id, mine in every.items():
        others = [v for other, v in every.items() if other != node_id]
        unique[node_id] = odfinger.ScreenViews(
            text=mine.text.difference(*(v.text for v in others)),
            structure=mine.structure.difference(*(v.structure for v in others)),
        )
    return unique


def _hits(
    identity: odfinger.ScreenViews, live: odfinger.ScreenViews
) -> Optional[int]:
    """
    Count identity hits; ``None`` when neither view covers the identity.
    """
    text = len(identity.text & live.text)
    structure = len(identity.structure & live.structure)
    fits = (
        identity.text
        and text / len(identity.text) >= odfinger.SAME_SCREEN_COVERAGE
    ) or (
        identity.structure
        and structure / len(identity.structure) >= odfinger.SAME_SCREEN_COVERAGE
    )
    return text + structure if fits else None


def _by_identity(
    nodes: collections.abc.Sequence[graph.Node],
    screen: digest.ScreenDigest,
    values: Dict[str, str],
    expected: Optional[str],
) -> Optional[Localization]:
    """
    Find the one node whose unique signatures are on the screen.
    """
    live = odfinger.views(odfinger.of(screen))
    by_id = {node.id: node for node in nodes}
    scored: Dict[str, int] = {}
    for node_id, identity in _unique_views(nodes).items():
        hits = _hits(identity, live)
        if hits is not None:
            scored[node_id] = hits
    if not scored:
        return None
    best = max(scored.values())
    tied = tuple(sorted(n for n, hits in scored.items() if hits == best))
    if len(tied) > 1 and expected not in tied:
        return Localization("ambiguous", candidates=tied, basis="identity")
    winner = tied[0] if len(tied) == 1 else str(expected)
    return _settled(by_id[winner], screen, values, "identity")


def _by_coverage(
    nodes: collections.abc.Sequence[graph.Node],
    screen: digest.ScreenDigest,
    values: Dict[str, str],
) -> Optional[Localization]:
    """
    Find the node most of whose fingerprint is on the screen.
    """
    screen_fp = set(odfinger.of(screen))
    scored: List[Tuple[float, bool, str]] = []
    for node in nodes:
        if not node.fingerprint:
            continue
        cover = odfinger.coverage(node.fingerprint, screen_fp)
        present = sum(1 for sig in node.fingerprint if sig in screen_fp)
        if cover >= odfinger.SAME_SCREEN_COVERAGE and present >= _MIN_PRESENT:
            scored.append((cover, _holds(node, screen, values), node.id))
    if not scored:
        return None
    scored.sort(key=lambda s: (-s[0], not s[1], s[2]))
    tied = [s for s in scored if s[:2] == scored[0][:2]]
    if len(tied) > 1:
        names = tuple(s[2] for s in tied)
        return Localization("ambiguous", candidates=names, basis="coverage")
    by_id = {node.id: node for node in nodes}
    return _settled(by_id[scored[0][2]], screen, values, "coverage")


def _by_checks(
    nodes: collections.abc.Sequence[graph.Node],
    screen: digest.ScreenDigest,
    values: Dict[str, str],
    expected: Optional[str],
    *,
    drifted: bool,
) -> Localization:
    """
    Find the node whose checks pass on the screen.

    :param nodes: the graph's nodes.
    :param screen: the live screen.
    :param values: task inputs for parameterised checks.
    :param expected: the node the path predicts.
    :param drifted: the content was consulted and did not match, so a
        passing check means the UI changed.
    :return: the result; ``unknown`` when no node's checks pass.
    """
    held = [node for node in nodes if _holds(node, screen, values)]
    if not held:
        return Localization("unknown", basis="checks")
    most = max(len(node.checks) for node in held)
    tied = [node for node in held if len(node.checks) == most]
    chosen = [node for node in tied if node.id == expected] or tied
    if len(chosen) > 1:
        names = tuple(sorted(node.id for node in chosen))
        return Localization("ambiguous", candidates=names, basis="checks")
    node = chosen[0]
    kind: Kind = "drifted" if drifted or _url_disagrees(node, screen) else "match"
    return Localization(kind, node.id, basis="checks")
