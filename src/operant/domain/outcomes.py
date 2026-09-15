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
import operant.domain.models.plan as plan


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


def unread_sibling(pattern: str, text: str, value: str) -> Optional[str]:
    """
    Find a sibling record a pattern anchored on ``value`` cannot read.

    A pattern recorded around an input (an account number, an order id)
    must read the record each replay's input names. Sibling records are
    other tokens on screen with the input's shape (same length; digits
    for digits, letters for letters). When swapping ``value`` for any of
    them reads that record's own value, the pattern generalizes; when
    none does (no match, or the same match as before), it only works for
    the discovery's record, e.g. because that record is the first row.

    :param pattern: The extraction regex, containing ``value``.
    :param text: The screen text it was written against.
    :param value: The input value inside the pattern.
    :return: A sibling to cite to the model, or ``None`` when the
        pattern generalizes or no sibling is visible.
    """
    original = re.search(pattern, text, re.IGNORECASE)
    if original is None or not value:
        return None
    group = 1 if original.groups() else 0
    shape = "".join(
        r"\d" if c.isdigit() else "[^\\W\\d_]" if c.isalpha() else re.escape(c)
        for c in value
    )
    siblings = list(
        dict.fromkeys(
            token
            for token in re.findall(rf"(?<!\w){shape}(?!\w)", text)
            if token != value
        )
    )[:5]
    unread = None
    for sibling in siblings:
        swapped = pattern.replace(re.escape(value), re.escape(sibling))
        swapped = swapped.replace(value, re.escape(sibling))
        match = re.search(swapped, text, re.IGNORECASE)
        if match is not None and match.span(group) != original.span(group):
            # One sibling reads its own record: the anchor works.
            return None
        unread = unread or sibling
    return unread


def failed_checks(
    checks: collections.abc.Sequence[plan.ScreenCheck],
    screen: Optional[digest.ScreenDigest],
    outputs: collections.abc.Mapping[str, str],
) -> List[str]:
    """
    Evaluate a subgoal's typed success checks; return what failed.

    :param checks: The planner's checks.
    :param screen: The current screen, if a window is bound.
    :param outputs: Values extracted so far.
    :return: One line per failed check; empty when all hold.
    """
    shown = ""
    names: List[str] = []
    if screen is not None:
        names = [f"{c.name} {c.label}".lower() for c in screen.controls]
        shown = " ".join([screen.text, screen.dialog or "", *names]).lower()
    failures: List[str] = []
    for check in checks:
        want = check.value.lower()
        if check.kind == "text_present":
            held = want in shown
        elif check.kind == "control_present":
            held = any(want in name for name in names)
        else:
            try:
                held = bool(re.search(check.value, outputs.get(check.output, "")))
            except re.error:
                held = False
        if not held:
            failures.append(f"{check.kind} {check.output} '{check.value}'")
    return [" ".join(f.split()) for f in failures]


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
