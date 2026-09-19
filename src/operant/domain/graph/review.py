"""
What a person's review of an unknown step is keyed on.

A review covers one edge acting on one control. A renamed control gets a
new key, so a person looks again; digits are masked so a row number or an
account does not count as a rename, and a parameterised name matches any
value.

Import as:

import operant.domain.graph.review as review
"""

from __future__ import annotations

import collections.abc
from typing import List, Optional, Tuple

import operant.domain.fingerprint as odfinger
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import operant.domain.models.targets as targets

ReviewKey = Tuple[str, str, str]


def _role_strategy(edge: graph.Edge) -> Optional[targets.RoleStrategy]:
    """
    Return the edge's role-and-name strategy, when it has one.
    """
    strategies = edge.target.strategies if edge.target is not None else []
    found = next(
        (s for s in strategies if isinstance(s, targets.RoleStrategy)), None
    )
    return found


def _label_strategy(edge: graph.Edge) -> Optional[targets.LabelProximityStrategy]:
    """
    Return the edge's label strategy, when it has one.
    """
    strategies = edge.target.strategies if edge.target is not None else []
    found = next(
        (s for s in strategies if isinstance(s, targets.LabelProximityStrategy)),
        None,
    )
    return found


def review_key(
    edge: graph.Edge, control: Optional[digest.Control] = None
) -> ReviewKey:
    """
    Return the key of a review of ``edge``.

    :param edge: the edge.
    :param control: the live control; ``None`` keys on the recorded one.
    :return: ``(edge id, role, normalised name)``.
    """
    recorded = _role_strategy(edge)
    anchored = _label_strategy(edge)
    role, name = "", ""
    if recorded is not None:
        role = recorded.role
        if "{{" not in recorded.name:
            name = control.name if control is not None else recorded.name
    elif anchored is not None:
        role = anchored.role
        if "{{" not in anchored.anchor_text:
            name = control.label if control is not None else anchored.anchor_text
    key = (edge.id, role, odfinger.normalize(name))
    return key


def unknown_steps(
    app_graph: graph.AppGraph, edge_ids: List[str]
) -> List[graph.Edge]:
    """
    Return the unknown steps of a path, in order.

    :param app_graph: the graph the path runs on.
    :param edge_ids: the path's edge ids.
    :return: the edges a person has to review.
    """
    edges = [app_graph.edge(edge_id) for edge_id in edge_ids]
    steps = [
        edge
        for edge in edges
        if edge.risk == "unknown" and edge.action.kind != "invoke"
    ]
    return steps


def outstanding_steps(
    app_graph: graph.AppGraph,
    edge_ids: List[str],
    is_approved: collections.abc.Callable[[ReviewKey], bool],
) -> List[graph.Edge]:
    """
    Return the unknown steps of a path nobody has reviewed yet.

    :param app_graph: the graph the path runs on.
    :param edge_ids: the path's edge ids.
    :param is_approved: whether a review with this key exists.
    :return: the edges a person still has to see.
    """
    steps = [
        edge
        for edge in unknown_steps(app_graph, edge_ids)
        if not is_approved(review_key(edge))
    ]
    return steps
