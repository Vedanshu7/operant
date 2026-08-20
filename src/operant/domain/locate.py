"""Pure resolution of a target-strategy stack against a screen digest.

No OS calls, no accessibility API, which keeps replay deterministic,
unit-testable, and portable to any surface that can produce a digest.

Typical usage example:

  found = resolve_target(edge.target.strategies, screen)
  if isinstance(found, Resolution):
      ref = found.control.ref

Import as:

import operant.domain.locate as locate
"""

from __future__ import annotations

import collections.abc
import dataclasses
import math
import re
from typing import List, Optional, Tuple, Union

import operant.domain.models.digest as digest
import operant.domain.models.targets as targets


def _norm(text: str) -> str:
    """
    Collapses whitespace and lower-cases for tolerant comparison.
    """
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    return normalized


# #############################################################################
# Resolution
# #############################################################################


@dataclasses.dataclass(frozen=True)
class Resolution:
    """
    A target stack resolved to exactly one control.

    :ivar control: The matched control.
    :ivar strategy_index: Position of the strategy that matched.
    :ivar strategy_kind: Kind of the strategy that matched.
    """

    control: digest.Control
    strategy_index: int
    strategy_kind: str


# #############################################################################
# ResolutionFailure
# #############################################################################


@dataclasses.dataclass(frozen=True)
class ResolutionFailure:
    """
    No strategy in the stack resolved to exactly one control.

    :ivar error:``not_found`` when nothing matched, ``ambiguous`` when
        some strategy matched more than one control.
    :ivar tried:``(strategy kind, match count)`` per strategy, in order.
    """

    error: str
    tried: Tuple[Tuple[str, int], ...]


def _match_role(
    strategy: targets.RoleStrategy, screen: digest.ScreenDigest
) -> List[digest.Control]:
    """
    Match by role and accessible name, exact first then substring.
    """
    want = _norm(strategy.name)
    exact = [
        c
        for c in screen.controls
        if c.role == strategy.role and _norm(c.name) == want
    ]
    if exact:
        matched = exact
    else:
        matched = [
            c
            for c in screen.controls
            if c.role == strategy.role and len(want) > 2 and want in _norm(c.name)
        ]
    return matched


def _match_label(
    strategy: targets.LabelProximityStrategy, screen: digest.ScreenDigest
) -> List[digest.Control]:
    """
    Match by role and anchoring label, exact first then substring.
    """
    anchor = _norm(strategy.anchor_text)
    exact = [
        c
        for c in screen.controls
        if c.role == strategy.role and _norm(c.label) == anchor
    ]
    if exact:
        matched = exact
    else:
        matched = [
            c
            for c in screen.controls
            if c.role == strategy.role
            and len(anchor) > 2
            and anchor in _norm(c.label)
        ]
    return matched


def _match_region(
    strategy: targets.RegionStrategy, screen: digest.ScreenDigest
) -> List[digest.Control]:
    """
    Match by role and centre distance within the tolerance.
    """
    cx = strategy.x + strategy.w / 2
    cy = strategy.y + strategy.h / 2
    matched = [
        c
        for c in screen.controls
        if c.role == strategy.role
        and math.hypot(c.box.x + c.box.w / 2 - cx, c.box.y + c.box.h / 2 - cy)
        <= strategy.tolerance
    ]
    return matched


def _match(
    strategy: targets.TargetStrategy, screen: digest.ScreenDigest
) -> List[digest.Control]:
    """
    Return every control one strategy matches.
    """
    if isinstance(strategy, targets.RoleStrategy):
        matched = _match_role(strategy, screen)
    elif isinstance(strategy, targets.LabelProximityStrategy):
        matched = _match_label(strategy, screen)
    elif isinstance(strategy, targets.StructuralStrategy):
        matched = [c for c in screen.controls if c.path == strategy.path]
    else:
        matched = _match_region(strategy, screen)
    return matched


def resolve_target(
    strategies: collections.abc.Sequence[targets.TargetStrategy],
    screen: digest.ScreenDigest,
) -> Union[Resolution, ResolutionFailure]:
    """
    Try each strategy in order until one matches exactly one control.

    A strategy matching zero or several controls falls through to the
    next, more structural one.

    :param strategies: The ranked strategy stack.
    :param screen: The digest to resolve against.
    :return: A ``Resolution`` on success, else a ``ResolutionFailure``
        that records what each strategy matched.
    """
    tried: List[Tuple[str, int]] = []
    result: Optional[Union[Resolution, ResolutionFailure]] = None
    for i, strategy in enumerate(strategies):
        matches = _match(strategy, screen)
        tried.append((strategy.kind, len(matches)))
        if len(matches) == 1:
            result = Resolution(
                control=matches[0],
                strategy_index=i,
                strategy_kind=strategy.kind,
            )
            break
    if result is None:
        error = "ambiguous" if any(n > 1 for _, n in tried) else "not_found"
        result = ResolutionFailure(error=error, tried=tuple(tried))
    return result
