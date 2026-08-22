"""
A scripted server harness: a real app whose runs drive a fake surface.

``build_app`` seeds a capability, graph, and profile into the file
repositories, then returns a FastAPI app whose run manager wires a
scripted surface instead of a macOS session. The scripted path clicks a
mutating control, so a replay blocks on an approval the tests answer
over HTTP.
"""

from __future__ import annotations

import pathlib
from typing import Dict, Optional, Tuple

import fastapi

import operant.application.context as context
import operant.application.escalation as escal
import operant.domain.models.artifact as artifact
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import operant.domain.policy as policy
import operant.domain.profile as dpprofil
import operant.domain.redaction as redact
import operant.infra.evidence.run_log as run_log
import operant.infra.repositories.graphs as rggraphs
import operant.infra.repositories.profiles as rpprofil
import operant.infra.settings as issettin
import operant.server.app as saapp
import tests.support.capabilities as capab
import tests.support.settings as sssettin
import tests.support.surfaces as surfaces

TOKEN = "test-token"

_POLICY = policy.Policy(
    id="p",
    allowed_apps=["App"],
    allowed_url_patterns=[".*"],
    allowed_action_kinds=["click", "fill", "press"],
    mutating_control_patterns=["send"],
)

_SCREENS: Dict[str, Tuple[str, Tuple[digest.Control, ...]]] = {
    "App | Home": (
        "Home",
        (
            digest.Control(
                ref="send",
                role="button",
                name="Send",
                label="",
                path="w>send",
                box=digest.Box(0.1, 0.1, 0.2, 0.05),
            ),
        ),
    ),
    "App | Done": ("done", ()),
}

_NODES = [
    capab.node("home", r"App \| Home"),
    capab.node("done", r"App \| Done"),
]


# #############################################################################
# _AppSurface
# #############################################################################


class _AppSurface(surfaces.GatedFakeSurface):
    """
    Advances through the scripted screens; ``close`` is a no-op.
    """

    def __init__(self) -> None:
        super().__init__(_POLICY)
        self._titles = ["App | Home", "App | Done"]
        self.title = self._titles.pop(0)
        self.app = "App"

    def snapshot(self) -> digest.ScreenDigest:
        text, controls = _SCREENS[self.title]
        return digest.ScreenDigest(
            app=self.app,
            window_title=self.title,
            text=text,
            controls=controls,
        )

    def apply(self, action: object) -> None:
        if self._titles:
            self.title = self._titles.pop(0)

    def start_human_capture(self, sink: object) -> None:
        """
        No live capture in tests.
        """

    def stop_human_capture(self) -> None:
        """
        No live capture in tests.
        """

    def close(self) -> None:
        """
        Nothing to release.
        """


# #############################################################################
# ScriptedFactory
# #############################################################################


class ScriptedFactory:
    """
    A context builder that wires the scripted surface for every run.
    """

    def __init__(self, settings: issettin.OperantSettings) -> None:
        self._settings = settings

    def build(
        self,
        kind: str,
        profile: dpprofil.AppProfile,
        *,
        approver: object = None,
        run_identifier: Optional[str] = None,
    ) -> context.RunContext:
        """
        Wire a run context around a fresh scripted surface.
        """
        run_id = run_identifier or "run"
        redactor = redact.Redactor()
        log = run_log.RunLog(
            self._settings.paths.evidence_dir, run_id, redactor, echo=False
        )
        surface = _AppSurface()
        broker = escal.ControlBroker(
            start_human_capture=surface.start_human_capture,
            stop_human_capture=surface.stop_human_capture,
            on_transition=lambda a, b, detail: None,
        )
        import operant.application.approval as approval

        return context.RunContext(
            run_id=run_id,
            settings=self._settings,
            redactor=redactor,
            log=log,
            surface=surface,
            health_table=lambda: [],
            broker=broker,
            approver=approver or approval.DenyAllApprover(),
        )


def _edge() -> graph.Edge:
    return capab.edge(
        {
            "id": "e1",
            "from": "home",
            "to": "done",
            "description": "send",
            "action": {"kind": "click"},
            "wait": {"kind": "settle", "timeout_ms": 1},
            "target": {
                "strategies": [
                    {"kind": "role", "role": "button", "name": "Send"}
                ],
                "reasoning": "r",
            },
        }
    )


def _profile() -> dpprofil.AppProfile:
    return dpprofil.AppProfile(
        vendor_id="p",
        app_name="App",
        window_title_pattern=r"App \| .*",
        policy=_POLICY,
        tenants={"t": artifact.TenantBinding(base_url="http://x")},
        default_tenant="t",
    )


def seed(settings: issettin.OperantSettings) -> str:
    """
    Write the capability, graph, and profile; returns the capability id.
    """
    graphs = rggraphs.FileGraphRepository(settings.paths.graphs_dir)
    profiles = rpprofil.FileProfileRepository(
        settings.paths.policies_dir, settings.paths.discovery_base_profile
    )
    import operant.infra.repositories.artifacts as raartifa

    artifacts = raartifa.FileArtifactRepository(settings.paths.artifacts_dir)
    capability = capab.capability(
        id="pay", name="Pay", start_node="home", goal_node="done"
    )
    graphs.save_new_version(
        graph.AppGraph(vendor_id="app", nodes=_NODES, edges=[_edge()])
    )
    artifacts.save_new_version(capability)
    profiles.save(_profile())
    return capability.id


def build_app(root: pathlib.Path) -> Tuple[fastapi.FastAPI, str]:
    """
    Build a scripted app and returns it with the seeded capability id.
    """
    settings = sssettin.test_settings(root)
    settings.server.cors_origins = []
    capability_id = seed(settings)
    app = saapp.create_app(settings, context_factory=ScriptedFactory(settings))
    return app, capability_id
