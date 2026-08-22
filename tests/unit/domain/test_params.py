from __future__ import annotations

from typing import List

import operant.domain.models.graph as graph
import operant.domain.models.targets as targets
import operant.domain.params as params

PARAMS = {"account": "13344", "user": "john"}


def test_substitute_strategies_replaces_role_name_and_anchor_text() -> None:
    stack: List[targets.TargetStrategy] = [
        targets.RoleStrategy(role="link", name="{{account}}"),
        targets.LabelProximityStrategy(
            anchor_text="Account {{account}}:", role="textbox"
        ),
        targets.StructuralStrategy(path="w>tr:{{account}}"),
        targets.RegionStrategy(role="button", x=0.1, y=0.1, w=0.1, h=0.1),
    ]
    out = params.substitute_strategies(stack, PARAMS)
    assert isinstance(out[0], targets.RoleStrategy)
    assert out[0].name == "13344"
    assert isinstance(out[1], targets.LabelProximityStrategy)
    assert out[1].anchor_text == "Account 13344:"
    assert out[2] is stack[2]
    assert out[3] is stack[3]
    # The recorded stack is never mutated.
    assert isinstance(stack[0], targets.RoleStrategy)
    assert stack[0].name == "{{account}}"


def test_substitute_strategies_leaves_unknown_placeholders_intact() -> None:
    stack: List[targets.TargetStrategy] = [
        targets.RoleStrategy(role="link", name="{{missing}} for {{user}}")
    ]
    out = params.substitute_strategies(stack, PARAMS)
    assert isinstance(out[0], targets.RoleStrategy)
    assert out[0].name == "{{missing}} for john"


def test_substitute_condition_rewrites_element_visible_only() -> None:
    visible = graph.ElementVisible(
        target=[targets.RoleStrategy(role="link", name="{{account}}")]
    )
    out = params.substitute_condition(visible, PARAMS)
    assert isinstance(out, graph.ElementVisible)
    assert isinstance(out.target[0], targets.RoleStrategy)
    assert out.target[0].name == "13344"
    assert isinstance(visible.target[0], targets.RoleStrategy)
    assert visible.target[0].name == "{{account}}"
    title = graph.TitleMatches(pattern="{{account}}")
    assert params.substitute_condition(title, PARAMS) is title
    text = graph.TextMatches(pattern="{{account}}")
    assert params.substitute_condition(text, PARAMS) is text
