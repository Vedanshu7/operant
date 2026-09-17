"""
Launch-first replay resumes from the live state by content.

A still-logged-in session re-localizes to the overview node after the
launch and skips the recorded login step; a logged-out session localizes
back to the login node and runs the full recorded path.
"""

from __future__ import annotations

import pathlib
import re
import types
from typing import List, Tuple

import operant.application.approval as approval
import operant.application.replay.engine as engine
import operant.domain.fingerprint as odfinger
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import operant.domain.policy as policy
import operant.domain.redaction as redact
import operant.infra.evidence.run_log as run_log
import tests.support.capabilities as capab
import tests.support.ports as ports
import tests.support.screens as screens
import tests.support.surfaces as surfaces
import tests.support.timing as timing

POLICY = policy.Policy(
    id="p",
    allowed_apps=["Chrome"],
    allowed_url_patterns=[".*"],
    allowed_action_kinds=["launch", "click"],
    mutating_control_patterns=["transfer", "send"],
)


_BOX = digest.Box(0.1, 0.1, 0.2, 0.05)


def _control(role: str, name: str, path: str) -> digest.Control:
    return screens.control(ref=name, role=role, name=name, path=path, box=_BOX)


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
    broker = ports.quiet_broker()
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
        timing.fast_replay_options(tenant="t", params={}),
        approver=approval.ScriptedApprover([]),
    )
    return result, surface


def test_already_logged_in_skips_the_login_step(tmp_path: pathlib.Path) -> None:
    result, surface = _run(tmp_path, ParabankSurface(logged_in=True))
    assert result.status == "success", result
    kinds = [a.kind for a in surface.performed]
    # The login click was skipped.
    assert kinds == ["launch"]


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
    Launch lands on a logged-in menu page that is not the goal page.

    Clicking "Accounts Overview" navigates to the real account page.
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
            # The logged-in index keeps the index title.
            window_title="Welcome",
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
    broker = ports.quiet_broker()
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
        timing.fast_replay_options(tenant="t", params={}),
        approver=approval.ScriptedApprover([]),
    )
    assert result.status == "success", result
    kinds = [a.kind for a in surface.performed]
    # Expect the launch and the menu-link click, never the recorded login click.
    assert kinds == ["launch", "click"]
    assert surface.performed[-1].ref == "Accounts Overview"


# -----------------------------------------------------------------------------
# Look-alike of an intermediate node: the landing shares the overview's menu,
# but the goal is one step further (an account's activity page).
# -----------------------------------------------------------------------------

ACTIVITY_TITLE = "ParaBank | Account Activity"
ACCOUNT_LINK = (_control("link", "13344", "content>table>row>link"),)
TRANSACTIONS = (
    _control("cell", "Funds Transfer Received", "content>activity>row>cell"),
    _control("cell", "Bill Payment", "content>activity>row>cell"),
)

DEEP_NODES = [
    *ADJ_NODES,
    graph.Node(
        id="activity",
        description="activity",
        checks=[graph.TitleMatches(pattern=re.escape(ACTIVITY_TITLE))],
        fingerprint=_fp(MENU + TRANSACTIONS),
    ),
]
DEEP_EDGES = [
    *ADJ_EDGES,
    capab.edge(
        {
            "id": "e3",
            "from": "overview",
            "to": "activity",
            "description": "open account {{accountId}}",
            "action": {"kind": "click"},
            "target": {
                "strategies": [
                    {"kind": "role", "role": "link", "name": "{{accountId}}"}
                ],
                "reasoning": "r",
            },
            "wait": {"kind": "settle", "timeout_ms": 1},
        }
    ),
]


# #############################################################################
# DeepLandingSurface
# #############################################################################


class DeepLandingSurface(LandingSurface):
    """
    Landing -> (Accounts Overview) -> overview -> (account link) -> activity.
    """

    def __init__(self) -> None:
        super().__init__()
        self._on_activity = False

    def snapshot(self) -> digest.ScreenDigest:
        if self._on_activity:
            return digest.ScreenDigest(
                app=self.app,
                window_title=ACTIVITY_TITLE,
                text="Balance: $10.00",
                controls=MENU + TRANSACTIONS,
            )
        shown = super().snapshot()
        if self._on_overview:
            shown = digest.ScreenDigest(
                app=shown.app,
                window_title=shown.window_title,
                text=shown.text,
                controls=shown.controls + ACCOUNT_LINK,
            )
        return shown

    def apply(self, action) -> None:
        if self._on_overview and action.kind == "click" and action.ref == "13344":
            self._on_activity = True
        super().apply(action)


def test_a_look_alike_of_an_intermediate_page_hops_onto_it_first(
    tmp_path: pathlib.Path,
) -> None:
    app_graph = graph.AppGraph(
        vendor_id="parabank", nodes=DEEP_NODES, edges=DEEP_EDGES
    )
    cap = capab.capability(
        vendor_id="parabank",
        start_node="login",
        goal_node="activity",
        compiled_path=["e1", "e2", "e3"],
    )
    surface = DeepLandingSurface()
    result = engine.replay_path(
        cap,
        app_graph,
        DEEP_EDGES,
        surface,
        ports.quiet_broker(),
        run_log.RunLog(tmp_path, "run", redact.Redactor(), echo=False),
        redact.Redactor(),
        timing.fast_replay_options(tenant="t", params={"accountId": "13344"}),
        approver=approval.ScriptedApprover([]),
    )
    assert result.status == "success", result
    assert [a.ref for a in surface.performed if a.kind == "click"] == [
        "Accounts Overview",
        "13344",
    ]


# #############################################################################
# GoalLandingSurface
# #############################################################################


class GoalLandingSurface(LandingSurface):
    """
    A live session sends the launch URL straight to the goal page.
    """

    def __init__(self) -> None:
        super().__init__()
        self._on_overview = True


def test_a_launch_landing_on_another_known_page_resumes_there(
    tmp_path: pathlib.Path,
) -> None:
    app_graph = graph.AppGraph(
        vendor_id="parabank", nodes=ADJ_NODES, edges=ADJ_EDGES
    )
    cap = capab.capability(
        vendor_id="parabank",
        start_node="login",
        goal_node="overview",
        compiled_path=["e1", "e2"],
    )
    surface = GoalLandingSurface()
    result = engine.replay_path(
        cap,
        app_graph,
        ADJ_EDGES,
        surface,
        ports.quiet_broker(),
        run_log.RunLog(tmp_path, "run", redact.Redactor(), echo=False),
        redact.Redactor(),
        timing.fast_replay_options(tenant="t", params={}),
        approver=approval.ScriptedApprover([]),
    )
    assert result.status == "success", result
    assert [a.kind for a in surface.performed] == ["launch"]


def test_a_home_page_that_passes_as_the_start_skips_ahead(
    tmp_path: pathlib.Path,
) -> None:
    # Fingerprints cannot separate them: the login node holds the whole menu.
    lookalike = [
        (
            node.model_copy(update={"fingerprint": _fp(LOGIN + MENU)})
            if node.id == "login"
            else node
        )
        for node in DEEP_NODES
    ]
    app_graph = graph.AppGraph(
        vendor_id="parabank", nodes=lookalike, edges=DEEP_EDGES
    )
    cap = capab.capability(
        vendor_id="parabank",
        start_node="login",
        goal_node="activity",
        compiled_path=["e1", "e2", "e3"],
    )
    surface = DeepLandingSurface()
    result = engine.replay_path(
        cap,
        app_graph,
        DEEP_EDGES,
        surface,
        ports.quiet_broker(),
        run_log.RunLog(tmp_path, "run", redact.Redactor(), echo=False),
        redact.Redactor(),
        timing.fast_replay_options(tenant="t", params={"accountId": "13344"}),
        approver=approval.ScriptedApprover([]),
    )
    assert result.status == "success", result
    assert [a.ref for a in surface.performed if a.kind == "click"] == [
        "Accounts Overview",
        "13344",
    ]


def test_a_brand_link_is_not_a_way_forward(tmp_path: pathlib.Path) -> None:
    brand = _control("link", "ParaBank", "content>logo>link")
    branded = [
        node.model_copy(
            update={
                "checks": [graph.TitleMatches(pattern=f"ParaBank {node.id}")],
                "description": node.id,
            }
        )
        for node in DEEP_NODES
    ]
    ctx = types.SimpleNamespace(
        graph=graph.AppGraph(
            vendor_id="parabank", nodes=branded, edges=DEEP_EDGES
        )
    )
    hop = capab.edge(
        {
            "id": "resume-nav",
            "from": "activity",
            "to": "activity",
            "description": brand.name,
            "action": {"kind": "click"},
        }
    )
    assert not engine._names_only(ctx, hop, ctx.graph.node("activity"))
