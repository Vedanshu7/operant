"""Task-input substitution into target strategies and conditions.

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
from typing import List

import operant.domain.models.graph as graph
import operant.domain.models.targets as targets
import operant.helpers.text as text


def substitute_strategies(
    strategies: collections.abc.Sequence[targets.TargetStrategy],
    params: collections.abc.Mapping[str, str],
) -> List[targets.TargetStrategy]:
    """
    Substitutes parameters into the textual parts of strategies.

    Role strategies substitute ``name``; label-proximity strategies
    substitute ``anchor_text``; structural and region strategies are
    returned unchanged.

    :param strategies: The recorded strategy stack.
    :param params: Task inputs keyed by placeholder name.
    :return: A new list of strategies with placeholders substituted.
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
    Substitutes parameters into an element-visible condition.

    Title and text conditions are returned unchanged.

    :param cond: The recorded condition.
    :param params: Task inputs keyed by placeholder name.
    :return: The condition with placeholders substituted in its target.
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
