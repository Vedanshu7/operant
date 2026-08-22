"""
Launch-first replay resumes from the live state by content.

A still-logged-in session re-localizes to the overview node after the
launch and skips the recorded login step; a logged-out session localizes
back to the login node and runs the full recorded path.
"""

from __future__ import annotations

import pathlib
import re
from typing import List, Tuple

import operant.application.approval as approval
import operant.application.escalation as escal
import operant.application.replay.engine as engine
import operant.application.replay.options as options
import operant.domain.fingerprint as odfinger
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import operant.domain.policy as policy
import operant.domain.redaction as redact
import operant.infra.evidence.run_log as run_log
import tests.support.capabilities as capab
import tests.support.surfaces as surfaces

POLICY = policy.Policy(
    id="p",
    allowed_apps=["Chrome"],
    allowed_url_patterns=[".*"],
    allowed_action_kinds=["launch", "click"],
    mutating_control_patterns=["transfer", "send"],
)


def _control(role: str, name: str, path: str) -> digest.Control:
    return digest.Control(
        ref=name,
        role=role,
        name=name,
        label="",
        path=path,
        box=digest.Box(0.1, 0.1, 0.2, 0.05),
    )


LOGIN = (
    _control("text_field", "Username", "content>form>text_field"),
    _control("text_field", "Password", "content>form>text_field"),
    _control("button", "Log In", "content>form>button"),
)
OVERVIEW = (
    _control("link", "Accounts Overview", "content>menu>link"),
    _control("link", "Log Out", "content>menu>link"),
)


def _fp(controls: Tuple[digest.Control, ...]) -> List[str]:
    return odfinger.of(
        digest.ScreenDigest(
            app="Chrome", window_title="Welcome", text="", controls=controls
        )
    )


# Both nodes keep the same "Welcome" title, as ParaBank's index does.
NODES = [
    graph.Node(
        id="login",
        description="login",
        checks=[graph.TitleMatches(pattern="Welcome")],
        fingerprint=_fp(LOGIN),
    ),
    graph.Node(
        id="overview",
        description="overview",
        checks=[graph.TitleMatches(pattern="Welcome")],
        fingerprint=_fp(OVERVIEW),
    ),
]
EDGES = [
    capab.edge(
        {
            "id": "e1",
            "from": "login",
            "to": "login",
            "description": "launch",
            "action": {"kind": "launch", "app": "Chrome", "url": "/index.htm"},
            "wait": {"kind": "settle", "timeout_ms": 1},
        }
    ),
    capab.edge(
        {
            "id": "e2",
            "from": "login",
            "to": "overview",
            "description": "log in",
            "action": {"kind": "click"},
            "target": {
                "strategies": [
                    {"kind": "role", "role": "button", "name": "Log In"}
                ],
                "reasoning": "r",
            },
            "wait": {"kind": "settle", "timeout_ms": 1},
        }
    ),
]


# #############################################################################
# ParabankSurface
# #############################################################################


class ParabankSurface(surfaces.GatedFakeSurface):
    """
    Launch lands on the index page; logged-in shows the overview content.
    """

    def __init__(self, logged_in: bool) -> None:
        super().__init__(POLICY)
        self._logged_in = logged_in
        self._advanced = False
        self.app = "Chrome"

    def snapshot(self) -> digest.ScreenDigest:
        controls = OVERVIEW if self._overview() else LOGIN
        return digest.ScreenDigest(
            app=self.app,
            window_title="Welcome",
            text="Accounts Overview" if self._overview() else "Customer Login",
            controls=controls,
        )

    def apply(self, action) -> None:
        if action.kind == "click":
            self._advanced = True

    def _overview(self) -> bool:
        return self._logged_in or self._advanced


def _run(tmp_path: pathlib.Path, surface: ParabankSurface):
    app_graph = graph.AppGraph(vendor_id="parabank", nodes=NODES, edges=EDGES)
    log = run_log.RunLog(tmp_path, "run", redact.Redactor(), echo=False)
    broker = escal.ControlBroker(
        start_human_capture=lambda cb: None,
        stop_human_capture=lambda: None,
        on_transition=lambda a, b, d: None,
    )
    cap = capab.capability(
        vendor_id="parabank",
        start_node="login",
        goal_node="overview",
        compiled_path=["e1", "e2"],
    )
    result = engine.replay_path(
        cap,
        app_graph,
        EDGES,
        surface,
        broker,
        log,
        redact.Redactor(),
        options.ReplayOptions(tenant="t", params={}),
        approver=approval.ScriptedApprover([]),
    )
    return result, surface


def test_already_logged_in_skips_the_login_step(tmp_path: pathlib.Path) -> None:
    result, surface = _run(tmp_path, ParabankSurface(logged_in=True))
    assert result.status == "success", result
    kinds = [a.kind for a in surface.performed]
    assert kinds == ["launch"]  # the login click was skipped


def test_logged_out_runs_the_full_login(tmp_path: pathlib.Path) -> None:
    result, surface = _run(tmp_path, ParabankSurface(logged_in=False))
    assert result.status == "success", result
    kinds = [a.kind for a in surface.performed]
    assert kinds == ["launch", "click"]


# -----------------------------------------------------------------------------
# Adjacent-to-goal: the logged-in landing looks like the account page (shared
# menu) but is not it, and carries a menu link named after the goal.
# -----------------------------------------------------------------------------

MENU = (
    _control("link", "Accounts Overview", "content>menu>link"),
    _control("link", "Transfer Funds", "content>menu>link"),
    _control("link", "Bill Pay", "content>menu>link"),
    _control("link", "Log Out", "content>menu>link"),
)
ACCOUNT_TABLE = (_control("cell", "Total $1,250.00", "content>table>row>cell"),)
GOAL_TITLE = "ParaBank | Accounts Overview"

ADJ_NODES = [
    graph.Node(
        id="login",
        description="login",
        checks=[graph.TitleMatches(pattern="Welcome")],
        fingerprint=_fp(LOGIN),
    ),
    graph.Node(
        id="overview",
        description="overview",
        checks=[graph.TitleMatches(pattern=re.escape(GOAL_TITLE))],
        fingerprint=_fp(MENU + ACCOUNT_TABLE),
    ),
]
ADJ_EDGES = [
    capab.edge(
        {
            "id": "e1",
            "from": "login",
            "to": "login",
            "description": "launch",
            "action": {"kind": "launch", "app": "Chrome", "url": "/index.htm"},
            "wait": {"kind": "settle", "timeout_ms": 1},
        }
    ),
    capab.edge(
        {
            "id": "e2",
            "from": "login",
            "to": "overview",
            "description": "log in",
            "action": {"kind": "click"},
            "target": {
                "strategies": [
                    {"kind": "role", "role": "button", "name": "Log In"}
                ],
                "reasoning": "r",
            },
            "wait": {"kind": "settle", "timeout_ms": 1},
        }
    ),
]


# #############################################################################
# LandingSurface
# #############################################################################


class LandingSurface(surfaces.GatedFakeSurface):
    """
    Launch lands on a logged-in menu page that is not the goal page; clicking
    "Accounts Overview" navigates to the real account page.
    """

    def __init__(self) -> None:
        super().__init__(POLICY)
        self.app = "Chrome"
        self._on_overview = False

    def snapshot(self) -> digest.ScreenDigest:
        if self._on_overview:
            return digest.ScreenDigest(
                app=self.app,
                window_title=GOAL_TITLE,
                text="Accounts Overview",
                controls=MENU + ACCOUNT_TABLE,
            )
        return digest.ScreenDigest(
            app=self.app,
            window_title="Welcome",  # logged-in index keeps the index title
            text="Welcome",
            controls=MENU,
        )

    def apply(self, action) -> None:
        if action.kind == "click" and (action.ref == "Accounts Overview"):
            self._on_overview = True


def test_adjacent_landing_navigates_to_goal_via_menu_link(
    tmp_path: pathlib.Path,
) -> None:
    app_graph = graph.AppGraph(
        vendor_id="parabank", nodes=ADJ_NODES, edges=ADJ_EDGES
    )
    log = run_log.RunLog(tmp_path, "run", redact.Redactor(), echo=False)
    broker = escal.ControlBroker(
        start_human_capture=lambda cb: None,
        stop_human_capture=lambda: None,
        on_transition=lambda a, b, d: None,
    )
    cap = capab.capability(
        vendor_id="parabank",
        start_node="login",
        goal_node="overview",
        compiled_path=["e1", "e2"],
    )
    surface = LandingSurface()
    result = engine.replay_path(
        cap,
        app_graph,
        ADJ_EDGES,
        surface,
        broker,
        log,
        redact.Redactor(),
        options.ReplayOptions(tenant="t", params={}),
        approver=approval.ScriptedApprover([]),
    )
    assert result.status == "success", result
    kinds = [a.kind for a in surface.performed]
    # launch, then the menu-link click - never the recorded login click.
    assert kinds == ["launch", "click"]
    assert surface.performed[-1].ref == "Accounts Overview"
