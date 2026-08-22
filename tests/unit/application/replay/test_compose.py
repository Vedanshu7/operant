"""
Cross-domain composition at the engine level: an invoke edge runs the
referenced graph and resumes; a nested failure bubbles to the caller.
"""

import pathlib
from typing import List, Tuple

import operant.application.escalation
import operant.application.replay.engine
import operant.application.replay.options
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import operant.domain.models.results as results
import operant.domain.redaction
import operant.infra.evidence.run_log as run_log
import tests.support.capabilities as capab

# #############################################################################
# ComposeSurface
# #############################################################################


class ComposeSurface:
    """
    Scripted surface: the title advances as edges and invokes act.
    """

    def __init__(self) -> None:
        self.title = "Chrome | Home"
        self.retargets: List[Tuple[str, str]] = []
        self.app_name = "Chrome"
        self.window_title_pattern = "Home"

    def snapshot(self) -> digest.ScreenDigest:
        return digest.ScreenDigest(
            app="app", window_title=self.title, text=self.title, controls=()
        )

    def perform(self, action, *, approval=None) -> object:
        if action.kind == "launch":
            self.title = "Settings | Pane"
        return None

    def retarget(self, app_name: str, pattern: str) -> Tuple[str, str]:
        prev = (self.app_name, self.window_title_pattern)
        self.retargets.append((app_name, pattern))
        self.app_name, self.window_title_pattern = app_name, pattern
        self.title = (
            "Settings | Pane" if "Settings" in pattern else "Chrome | Goal"
        )
        return prev

    def target_text_for(self, ref):
        return ""

    def screenshot(self, path: pathlib.Path) -> bool:
        return False


INVOKE_EDGE = capab.edge(
    {
        "id": "e1",
        "from": "home",
        "to": "goal",
        "description": "check a system setting",
        "action": {
            "kind": "invoke",
            "graph_ref": {"graph_id": "settings", "target_node": "pane"},
        },
    }
)

GRAPH = graph.AppGraph(
    vendor_id="chrome",
    app_name="Chrome",
    window_title_pattern="Chrome",
    nodes=[
        capab.node("home", "Home"),
        capab.node("goal", "Goal"),
    ],
    edges=[INVOKE_EDGE],
)


def _run(tmp_path: pathlib.Path, invoke):
    log = run_log.RunLog(
        tmp_path, "compose", operant.domain.redaction.Redactor(), echo=False
    )
    broker = operant.application.escalation.ControlBroker(
        start_human_capture=lambda cb: None,
        stop_human_capture=lambda: None,
        on_transition=lambda a, b, d: None,
    )
    surface = ComposeSurface()
    cap = capab.capability(vendor_id="chrome", compiled_path=["e1"])
    result = operant.application.replay.engine.replay_path(
        cap,
        GRAPH,
        [INVOKE_EDGE],
        surface,
        broker,
        log,
        operant.domain.redaction.Redactor(),
        operant.application.replay.options.ReplayOptions(tenant="t", params={}),
        invoke_graph=invoke,
        depth=0,
    )
    return result, surface


def test_invoke_edge_runs_referenced_graph_and_resumes(
    tmp_path: pathlib.Path,
) -> None:
    calls: List[graph.GraphRef] = []

    def invoke(ref: graph.GraphRef, ctx) -> None:
        calls.append(ref)
        ctx.surface.title = "Chrome | Goal"
        return None

    result, surface = _run(tmp_path, invoke)
    assert result.status == "success"
    assert surface.retargets == []
    assert [r.graph_id for r in calls] == ["settings"]


def test_invoke_failure_bubbles_up(tmp_path: pathlib.Path) -> None:
    def invoke(ref, ctx):
        return results.FailureResult(
            failure=results.Failure(
                at_edge="x",
                failure_class="app_error",
                expected="e",
                observed="o",
            ),
            evidence_dir="d",
        )

    result, _ = _run(tmp_path, invoke)
    assert result.status == "failure"
