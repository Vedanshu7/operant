"""
Replay never repeats a step that changes data: when a submitted mutation's next
page fails to show, a person checks instead of a retry, which could submit it
twice.
"""

import threading
import time
from typing import Dict, List, Tuple

import operant.application.approval
import operant.application.escalation
import operant.application.replay.engine
import operant.application.replay.options
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import operant.domain.policy as policy
import operant.domain.redaction
import operant.infra.evidence.run_log as run_log
import tests.support.capabilities as capab
import tests.support.surfaces as surfaces

POLICY = policy.Policy(
    id="p",
    allowed_apps=["App"],
    allowed_url_patterns=[".*"],
    allowed_action_kinds=["click"],
    mutating_control_patterns=["send"],
)

HOME_CONTROLS = (
    digest.Control(
        ref="send",
        role="button",
        name="Send",
        label="",
        path="w>send",
        box=digest.Box(0.1, 0.1, 0.2, 0.05),
    ),
    digest.Control(
        ref="refresh",
        role="button",
        name="Refresh",
        label="",
        path="w>refresh",
        box=digest.Box(0.4, 0.1, 0.2, 0.05),
    ),
)

# The busy page keeps the form, as a server error page with a retry does.
SCREENS: Dict[str, Tuple[str, Tuple[digest.Control, ...]]] = {
    "App | Home": ("Inbox", HOME_CONTROLS),
    "App | Busy": ("Server busy - try again", HOME_CONTROLS),
    "App | Done": ("done", ()),
}

NODES = [
    capab.node("home", r"App \| Home"),
    capab.node("done", r"App \| Done"),
]

RETRY_WHEN_BUSY = graph.OutcomeEdge(
    id="busy",
    at="done",
    when=graph.TextMatches(pattern="try again"),
    handle=graph.RecoverHandle(recovery="retryEdge"),
)


# #############################################################################
# BusyOnceSurface
# #############################################################################


class BusyOnceSurface(surfaces.GatedFakeSurface):
    """
    The first click lands on a busy page; any later click reaches Done.
    """

    def __init__(self) -> None:
        super().__init__(POLICY)
        self.title = "App | Home"
        self.app = "App"

    def snapshot(self) -> digest.ScreenDigest:
        text, controls = SCREENS[self.title]
        return digest.ScreenDigest(
            app=self.app, window_title=self.title, text=text, controls=controls
        )

    def apply(self, action) -> None:
        self.title = "App | Busy" if len(self.performed) == 1 else "App | Done"


def _click(name: str, risk: str) -> graph.Edge:
    return capab.edge(
        {
            "id": "e1",
            "from": "home",
            "to": "done",
            "description": f"click {name}",
            "action": {"kind": "click"},
            "risk": risk,
            "wait": {"kind": "settle", "timeout_ms": 1},
            "target": {
                "strategies": [{"kind": "role", "role": "button", "name": name}],
                "reasoning": "r",
            },
        }
    )


def _run(tmp_path, edge, surface, broker, approver):
    cap = capab.capability(start_node="home", goal_node="done")
    app_graph = graph.AppGraph(
        vendor_id=cap.vendor_id,
        nodes=NODES,
        edges=[edge],
        outcome_edges=[RETRY_WHEN_BUSY],
    )
    log = run_log.RunLog(
        tmp_path, "run", operant.domain.redaction.Redactor(), echo=False
    )
    opts = operant.application.replay.options.ReplayOptions(
        tenant="t", params={}, retry_delay_s=0
    )
    return operant.application.replay.engine.replay_path(
        cap,
        app_graph,
        [edge],
        surface,
        broker,
        log,
        log.redactor,
        opts,
        approver=approver,
    )


def _broker() -> operant.application.escalation.ControlBroker:
    return operant.application.escalation.ControlBroker(
        start_human_capture=lambda cb: None,
        stop_human_capture=lambda: None,
        on_transition=lambda a, b, d: None,
    )


def _person(
    broker, surface, *, finish: bool, seen: List[str]
) -> threading.Thread:
    """
    Answer the run's one escalation: finish the step by hand, or give up.
    """

    def act() -> None:
        while broker.pending is None:
            time.sleep(0.005)
        request = broker.pending
        seen.append(request.reason)
        if finish:
            broker.take_control(request.id)
            surface.title = "App | Done"
            broker.hand_back(request.id, "checked: it went through")
        else:
            broker.abandon(request.id, "not sure")

    worker = threading.Thread(target=act, daemon=True)
    worker.start()
    return worker


def test_a_safe_step_is_retried(tmp_path):
    surface = BusyOnceSurface()
    approver = operant.application.approval.ScriptedApprover([])
    result = _run(
        tmp_path, _click("Refresh", "safe"), surface, _broker(), approver
    )
    assert result.status == "success", result
    assert len(surface.performed) == 2


def test_a_submitted_mutation_goes_to_a_person_not_a_retry(tmp_path):
    surface = BusyOnceSurface()
    broker = _broker()
    seen: List[str] = []
    worker = _person(broker, surface, finish=True, seen=seen)
    approver = operant.application.approval.ScriptedApprover([True, True])
    result = _run(tmp_path, _click("Send", "mutating"), surface, broker, approver)
    worker.join(timeout=2)
    assert result.status == "success", result
    assert len(surface.performed) == 1
    assert len(approver.asked) == 1
    assert "already" in seen[0]


def test_a_person_can_stop_an_unconfirmed_mutation(tmp_path):
    surface = BusyOnceSurface()
    broker = _broker()
    worker = _person(broker, surface, finish=False, seen=[])
    approver = operant.application.approval.ScriptedApprover([True, True])
    result = _run(tmp_path, _click("Send", "mutating"), surface, broker, approver)
    worker.join(timeout=2)
    assert result.status == "escalated", result
    assert len(surface.performed) == 1
