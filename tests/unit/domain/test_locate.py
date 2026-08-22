from __future__ import annotations

from typing import List

import pytest

import operant.domain.locate as locate
import operant.domain.models.digest as digest
import operant.domain.models.targets as targets
import tests.support.screens as screens

RESOLVE_CASES = [
    (
        "role + accessible name, exact",
        [
            screens.control(ref="c1", role="link", name="13344"),
            screens.control(ref="c2", role="link", name="13455"),
        ],
        [targets.RoleStrategy(role="link", name="13344")],
        "c1",
        0,
    ),
    (
        "case/whitespace-insensitive names",
        [screens.control(ref="c1", role="button", name="Log  In")],
        [targets.RoleStrategy(role="button", name="log in")],
        "c1",
        0,
    ),
    (
        "ambiguous role falls through to structural",
        [
            screens.control(
                ref="c1", role="textbox", name="amount", path="w>tr:1>input"
            ),
            screens.control(
                ref="c2", role="textbox", name="amount", path="w>tr:2>input"
            ),
        ],
        [
            targets.RoleStrategy(role="textbox", name="amount"),
            targets.StructuralStrategy(path="w>tr:2>input"),
        ],
        "c2",
        1,
    ),
    (
        "label proximity for legacy layouts",
        [
            screens.control(ref="c1", role="textbox", label="Username:"),
            screens.control(ref="c2", role="textbox", label="Password:"),
        ],
        [targets.LabelProximityStrategy(anchor_text="Password:", role="textbox")],
        "c2",
        0,
    ),
    (
        "region geometry as last resort",
        [
            screens.control(
                ref="c1",
                role="button",
                box=digest.Box(0.4, 0.4, 0.1, 0.05),
            ),
            screens.control(
                ref="c2",
                role="button",
                box=digest.Box(0.8, 0.8, 0.1, 0.05),
            ),
        ],
        [targets.RegionStrategy(role="button", x=0.41, y=0.39, w=0.1, h=0.05)],
        "c1",
        0,
    ),
]


@pytest.mark.parametrize(
    ("name", "controls", "strategies", "want_ref", "want_index"), RESOLVE_CASES
)
def test_resolves(
    name: str,
    controls: List[digest.Control],
    strategies: List[targets.TargetStrategy],
    want_ref: str,
    want_index: int,
) -> None:
    r = locate.resolve_target(strategies, screens.digest(controls))
    assert isinstance(r, locate.Resolution), name
    assert r.control.ref == want_ref
    assert r.strategy_index == want_index


def test_not_found_reports_tried_strategies() -> None:
    r = locate.resolve_target(
        [
            targets.RoleStrategy(role="link", name="99999"),
            targets.LabelProximityStrategy(anchor_text="nope", role="link"),
        ],
        screens.digest([screens.control(ref="c1", role="link", name="13344")]),
    )
    assert isinstance(r, locate.ResolutionFailure)
    assert r.error == "not_found"
    assert len(r.tried) == 2


def test_ambiguous_when_no_strategy_unique() -> None:
    d = screens.digest(
        [
            screens.control(ref="c1", role="button", name="Transfer"),
            screens.control(ref="c2", role="button", name="Transfer"),
        ]
    )
    r = locate.resolve_target(
        [targets.RoleStrategy(role="button", name="Transfer")], d
    )
    assert isinstance(r, locate.ResolutionFailure)
    assert r.error == "ambiguous"
