"""
Replay primitives: select with a parameterised option, window scroll, and
coordinate-click replay of a region-only recorded target.
"""

import pathlib
from typing import Dict, Tuple

import pytest

import operant.application.escalation
import operant.application.replay.engine
import operant.application.replay.options
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import operant.domain.models.targets as targets
import operant.domain.redaction
import operant.infra.evidence.run_log as run_log
import tests.support.capabilities as capab
import tests.support.surfaces as surfaces

# #############################################################################
# FormSurface
# #############################################################################


class FormSurface(surfaces.TitledSurface):
    """
    One screen with a combo box; any action advances the title.
    """

    def __init__(self) -> None:
        super().__init__(["App | Form", "App | Done"])

    def controls_for(self, title: str) -> Tuple[digest.Control, ...]:
        return (
            digest.Control(
                ref="c0",
                role="combo_box",
                name="Type",
                label="Type",
                path="w>combo",
                box=digest.Box(0.4, 0.4, 0.2, 0.05),
            ),
        )


def _replay(tmp_path: pathlib.Path, edge: graph.Edge, params: Dict[str, str]):
    app_graph = graph.AppGraph(
        vendor_id="app",
        nodes=[
            capab.node("form", r"App \| Form"),
            capab.node("done", r"App \| Done"),
        ],
        edges=[edge],
    )
    surface = FormSurface()
    log = run_log.RunLog(
        tmp_path, "run", operant.domain.redaction.Redactor(), echo=False
    )
    broker = operant.application.escalation.ControlBroker(
        start_human_capture=lambda cb: None,
        stop_human_capture=lambda: None,
        on_transition=lambda a, b, d: None,
    )
    cap = capab.capability(
        start_node="form", goal_node="done", compiled_path=["e1"]
    )
    result = operant.application.replay.engine.replay_path(
        cap,
        app_graph,
        [edge],
        surface,
        broker,
        log,
        operant.domain.redaction.Redactor(),
        operant.application.replay.options.ReplayOptions(
            tenant="t", params=params
        ),
    )
    return result, surface


def test_select_substitutes_the_option_param(tmp_path: pathlib.Path) -> None:
    edge = capab.edge(
        {
            "id": "e1",
            "from": "form",
            "to": "done",
            "description": "choose type",
            "action": {"kind": "select", "option": {"param": "accountType"}},
            "target": {
                "strategies": [
                    {"kind": "role", "role": "combo_box", "name": "Type"}
                ],
                "reasoning": "r",
            },
            "wait": {"kind": "settle", "timeout_ms": 1},
        }
    )
    result, surface = _replay(tmp_path, edge, {"accountType": "SAVINGS"})
    assert result.status == "success"
    performed = surface.performed[0]
    assert performed.kind == "select" and performed.ref == "c0"
    assert performed.option == "SAVINGS"


def test_window_scroll_needs_no_target(tmp_path: pathlib.Path) -> None:
    edge = capab.edge(
        {
            "id": "e1",
            "from": "form",
            "to": "done",
            "description": "scroll down",
            "action": {"kind": "scroll", "direction": "down", "amount": 3},
            "wait": {"kind": "settle", "timeout_ms": 1},
        }
    )
    result, surface = _replay(tmp_path, edge, {})
    assert result.status == "success"
    performed = surface.performed[0]
    assert performed.kind == "scroll"
    assert performed.direction == "down" and performed.amount == 3


def test_region_only_target_replays_as_coordinate_click(
    tmp_path: pathlib.Path,
) -> None:
    target = targets.Target(
        strategies=[
            targets.RegionStrategy(
                role="region", x=0.70, y=0.29, w=0.04, h=0.04, tolerance=0.05
            )
        ],
        reasoning="vision-grounded click point for the unlabeled gear icon",
    )
    edge = capab.edge(
        {
            "id": "e1",
            "from": "form",
            "to": "done",
            "description": "the unlabeled gear icon",
            "action": {"kind": "click"},
            "target": target.model_dump(),
            "wait": {"kind": "settle", "timeout_ms": 1},
        }
    )
    result, surface = _replay(tmp_path, edge, {})
    assert result.status == "success"
    performed = surface.performed[0]
    assert performed.kind == "click" and performed.ref is None
    assert performed.x == pytest.approx(0.72)
    assert performed.y == pytest.approx(0.31)
