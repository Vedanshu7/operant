"""Condition evaluation, outcome-edge matching, and output extraction.

All pure functions over a screen digest.

Typical usage example:

  edge = match_outcome_edges(graph.outcome_edges, node_id, screen)
  outputs, missing = run_extraction(capability.extract, screen)

Import as:

import operant.domain.outcomes as outcomes
"""

from __future__ import annotations

import collections.abc
import re
from typing import Dict, List, Optional, Tuple

import operant.domain.locate as locate
import operant.domain.models.artifact as artifact
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph


def evaluate_condition(
    cond: graph.Condition, screen: digest.ScreenDigest
) -> bool:
    """
    Report whether a condition holds on the digest.

    :param cond: A title, text, or element-visible condition.
    :param screen: The digest to test against.
    :return:``True`` when the condition holds.
    """
    if cond.kind == "titleMatches":
        # Title condition: match the pattern against the window title.
        held = (
            re.search(cond.pattern, screen.window_title, re.IGNORECASE)
            is not None
        )
    elif cond.kind == "textMatches":
        # Text condition: search the visible text, dialog included.
        haystack = screen.text
        if screen.dialog:
            haystack = f"{screen.text}\n{screen.dialog}"
        held = re.search(cond.pattern, haystack, re.IGNORECASE) is not None
    else:
        # Element-visible condition: the target must resolve on screen.
        held = isinstance(
            locate.resolve_target(cond.target, screen), locate.Resolution
        )
    result = held != cond.negate
    return result


def on_node(
    node_checks: collections.abc.Sequence[graph.Condition],
    screen: digest.ScreenDigest,
) -> bool:
    """
    Report whether every check of a node holds on the digest.

    :param node_checks: The node's conditions.
    :param screen: The digest to test against.
    :return:``True`` when all checks hold.
    """
    holds = all(evaluate_condition(c, screen) for c in node_checks)
    return holds


def match_outcome_edges(
    outcome_edges: collections.abc.Sequence[graph.OutcomeEdge],
    at_node: str,
    screen: digest.ScreenDigest,
) -> Optional[graph.OutcomeEdge]:
    """
    Find the first outcome edge whose condition holds.

    Node-scoped outcome edges rank before global (``*``) ones.

    :param outcome_edges: Every outcome edge in play.
    :param at_node: The node the run is at.
    :param screen: The digest to test against.
    :return: The first matching edge, or ``None``.
    """
    scoped = [e for e in outcome_edges if e.at == at_node]
    global_ = [e for e in outcome_edges if e.at == "*"]
    matched = None
    for edge in [*scoped, *global_]:
        if evaluate_condition(edge.when, screen):
            matched = edge
            break
    return matched


def extract_one(pattern: str, text: str) -> Optional[str]:
    """
    Apply the single extraction rule shared by every reader.

    :param pattern: Regex searched case-insensitively.
    :param text: The text to search.
    :return: Group 1 (or the whole match), stripped; ``None`` when
        absent.
    """
    m = re.search(pattern, text, re.IGNORECASE)
    if m is None:
        result = None
    else:
        value = m.group(1) if m.groups() else m.group(0)
        result = value.strip()
    return result


def run_extraction(
    specs: collections.abc.Sequence[artifact.ExtractSpec],
    screen: digest.ScreenDigest,
) -> Tuple[Dict[str, str], List[str]]:
    """
    Read every declared output from the digest text.

    :param specs: Output name and pattern per output.
    :param screen: The digest to read from.
    :return:``(outputs found, names of outputs not found)``.
    """
    outputs: Dict[str, str] = {}
    missing: List[str] = []
    for spec in specs:
        value = extract_one(spec.pattern, screen.text)
        if value is None:
            missing.append(spec.output)
        else:
            outputs[spec.output] = value
    return outputs, missing
