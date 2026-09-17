"""
Task-input substitution into target strategies and conditions.

Recorded strategies and element-visible conditions may carry
``{{name}}`` placeholders for task inputs (e.g. an account number in a
link name). Replay substitutes the run's parameters before resolving.
Unknown placeholders are left intact so a missing input is visible.

Typical usage example:

  strategies = substitute_strategies(edge.target.strategies, params)

Import as:

import operant.domain.params as params
"""

from __future__ import annotations

import collections.abc
import re
from typing import List

import operant.domain.models.graph as graph
import operant.domain.models.targets as targets
import operant.helpers.text as text


def substitute_strategies(
    strategies: collections.abc.Sequence[targets.TargetStrategy],
    params: collections.abc.Mapping[str, str],
) -> List[targets.TargetStrategy]:
    """
    Substitute parameters into the textual parts of strategies.

    Role strategies substitute ``name``; label-proximity strategies
    substitute ``anchor_text``; structural and region strategies are
    returned unchanged.

    :param strategies: the recorded strategy stack.
    :param params: task inputs keyed by placeholder name.
    :return: new strategies with placeholders substituted.
    """
    out: List[targets.TargetStrategy] = []
    for strategy in strategies:
        if isinstance(strategy, targets.RoleStrategy):
            # Role strategy: substitute into the accessible name.
            name = text.substitute_placeholders(strategy.name, params)
            out.append(strategy.model_copy(update={"name": name}))
        elif isinstance(strategy, targets.LabelProximityStrategy):
            # Label-proximity strategy: substitute into the anchor text.
            anchor = text.substitute_placeholders(strategy.anchor_text, params)
            out.append(strategy.model_copy(update={"anchor_text": anchor}))
        else:
            # Structural and region strategies carry no text: pass through.
            out.append(strategy)
    return out


def substitute_condition(
    cond: graph.Condition, params: collections.abc.Mapping[str, str]
) -> graph.Condition:
    """
    Substitute parameters into an element-visible condition.

    Title and text conditions are returned unchanged.

    :param cond: the recorded condition.
    :param params: task inputs keyed by placeholder name.
    :return: the condition with placeholders substituted in its target.
    """
    result: graph.Condition
    if isinstance(cond, graph.ElementVisible):
        # Element-visible condition: substitute into its target stack.
        result = cond.model_copy(
            update={"target": substitute_strategies(cond.target, params)}
        )
    else:
        # Title and text conditions carry no target: pass through.
        result = cond
    return result


def substitute_pattern(
    pattern: str, params: collections.abc.Mapping[str, str]
) -> str:
    """
    Fill ``{{name}}`` placeholders in a regex with escaped input values.

    :param pattern: a recorded extraction pattern.
    :param params: task inputs keyed by placeholder name.
    :return: the pattern for this run; unknown placeholders are left in
        place so a missing input is visible.
    """
    filled = pattern
    for name, value in params.items():
        filled = filled.replace(f"{{{{{name}}}}}", re.escape(value))
    return filled
