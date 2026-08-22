"""
Capability-scoped extraction at replay: read at extract_at_node (goal or mid-
path), hard-fail when the extraction node was never reached.
"""

import pathlib
from typing import List, Optional, Tuple

import operant.application.escalation
import operant.application.replay.engine
import operant.application.replay.options
import operant.domain.models.artifact as artifact
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import operant.domain.redaction
import operant.infra.evidence.run_log as run_log
import tests.support.capabilities as capab
import tests.support.surfaces as surfaces

TEXTS = {
    "App | Home": "welcome",
    "App | Mid": "Balance: $42.00",
    "App | Goal": "done",
}

TITLES = ["App | Home", "App | Mid", "App | Goal"]


def _edge(eid: str, from_node: str, to_node: str) -> graph.Edge:
    return capab.edge(
        {
            "id": eid,
            "from": from_node,
            "to": to_node,
            "description": eid,
            "action": {"kind": "press", "key": "Enter"},
            "wait": {"kind": "settle", "timeout_ms": 1},
        }
    )


GRAPH = graph.AppGraph(
    vendor_id="app",
    nodes=[
        capab.node("home", r"App \| Home"),
        capab.node("mid", r"App \| Mid"),
        capab.node("goal", r"App \| Goal"),
        capab.node("unvisited", "Nowhere"),
    ],
    edges=[_edge("e1", "home", "mid"), _edge("e2", "mid", "goal")],
)


def _broker() -> operant.application.escalation.ControlBroker:
    return operant.application.escalation.ControlBroker(
        start_human_capture=lambda cb: None,
        stop_human_capture=lambda: None,
        on_transition=lambda a, b, d: None,
    )


def _run(
    tmp_path: pathlib.Path,
    cap: artifact.CapabilityArtifact,
    app_graph=GRAPH,
    surface=None,
):
    log = run_log.RunLog(
        tmp_path, "run", operant.domain.redaction.Redactor(), echo=False
    )
    surface = surface or surfaces.TitledSurface(TITLES, TEXTS)
    path = [app_graph.edge(e) for e in cap.compiled_path]
    return (
        operant.application.replay.engine.replay_path(
            cap,
            app_graph,
            path,
            surface,
            _broker(),
            log,
            operant.domain.redaction.Redactor(),
            operant.application.replay.options.ReplayOptions(
                tenant="t", params={}
            ),
        ),
        surface,
    )


def _cap(**over):
    over.setdefault("compiled_path", ["e1", "e2"])
    return capab.capability(**over)


def test_extract_at_goal(tmp_path: pathlib.Path) -> None:
    cap = _cap(
        extract_at_node="goal",
        extract=[artifact.ExtractSpec(output="status", pattern="(done)")],
    )
    result, _ = _run(tmp_path, cap)
    assert result.status == "success"
    assert result.outputs == {"status": "done"}


def test_extract_at_mid_path_node_uses_that_screen(
    tmp_path: pathlib.Path,
) -> None:
    cap = _cap(
        extract_at_node="mid",
        extract=[
            artifact.ExtractSpec(
                output="balance", pattern=r"Balance: \$([0-9.]+)"
            )
        ],
    )
    result, _ = _run(tmp_path, cap)
    assert result.status == "success"
    assert result.outputs == {"balance": "42.00"}


def test_extraction_node_never_reached_fails(tmp_path: pathlib.Path) -> None:
    cap = _cap(
        extract_at_node="unvisited",
        extract=[artifact.ExtractSpec(output="x", pattern="(x)")],
    )
    result, _ = _run(tmp_path, cap)
    assert result.status == "failure"
    assert "never reached" in result.failure.observed


def test_missing_output_at_extract_node_fails(tmp_path: pathlib.Path) -> None:
    cap = _cap(
        extract_at_node="goal",
        extract=[
            artifact.ExtractSpec(output="absent", pattern="such value: (\\d+)")
        ],
    )
    result, _ = _run(tmp_path, cap)
    assert result.status == "failure"
    assert result.failure.expected.startswith("extractable outputs")


# #############################################################################
# FillSurface
# #############################################################################


class FillSurface(surfaces.TitledSurface):
    """
    The Mid screen has a text field; fills are captured for assertion.
    """

    def __init__(self) -> None:
        super().__init__(TITLES, TEXTS)
        self.filled: List[Optional[str]] = []

    def controls_for(self, title: str) -> Tuple[digest.Control, ...]:
        if title != "App | Mid":
            return ()
        return (
            digest.Control(
                ref="c0",
                role="text_field",
                name="Amount",
                label="",
                path="w>tf",
                box=digest.Box(0.1, 0.1, 0.2, 0.05),
            ),
        )

    def perform(self, action, *, approval=None):
        if action.kind == "fill":
            self.filled.append(action.value)
        return super().perform(action, approval=approval)


def test_fill_from_output_reads_the_eagerly_extracted_value(
    tmp_path: pathlib.Path,
) -> None:
    fill_edge = capab.edge(
        {
            "id": "e2b",
            "from": "mid",
            "to": "goal",
            "description": "type the balance",
            "action": {"kind": "fill", "value": {"from_output": "balance"}},
            "target": {
                "strategies": [
                    {"kind": "role", "role": "text_field", "name": "Amount"}
                ],
                "reasoning": "r",
            },
            "wait": {"kind": "settle", "timeout_ms": 1},
        }
    )
    app_graph = graph.AppGraph(
        vendor_id="app", nodes=GRAPH.nodes, edges=[GRAPH.edge("e1"), fill_edge]
    )
    cap = _cap(
        compiled_path=["e1", "e2b"],
        extract_at_node="mid",
        extract=[
            artifact.ExtractSpec(
                output="balance", pattern=r"Balance: \$([0-9.]+)"
            )
        ],
    )
    result, surface = _run(tmp_path, cap, app_graph, FillSurface())
    assert result.status == "success"
    assert surface.filled == ["42.00"]
