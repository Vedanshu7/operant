"""
A driver daemon over ASGI with a scripted gateway behind it.

Import as:

import tests.support.driver as driver
"""

from __future__ import annotations

import pathlib
from typing import List, Optional, Tuple

import fastapi.testclient as testclie

import operant.adapters.http.driver.app as app
import operant.application.gateway.registry as registry
import operant.domain.approval as daapprov
import operant.domain.errors as errors
import operant.domain.models.actions as actions
import operant.domain.models.digest as digest
import operant.domain.redaction as redact

# #############################################################################
# FakeGatewaySurface
# #############################################################################


class FakeGatewaySurface:
    """
    A gateway surface that gates ``mutating`` steps and denies ``denied`` ones.
    """

    def __init__(self) -> None:
        self.performed: List[actions.SurfaceAction] = []
        self.grants: List[daapprov.ScopeGrant] = []

    def snapshot(self) -> digest.ScreenDigest:
        return digest.ScreenDigest(app="App", window_title="Home", text="hi")

    def perform(self, action, *, approval=None):
        self.performed.append(action)
        if action.step == "mutating":
            request = daapprov.ApprovalRequest(
                kind="mutating", summary="click Transfer", action_kind="click"
            )
            raise errors.ApprovalRequiredError(request, "nonce-1", action)
        if action.step == "denied":
            raise errors.PolicyViolationError(
                daapprov.PolicyDecision(
                    verdict="deny", risk="mutating", reason="not allowed"
                )
            )
        return {"tool": "ax-action", "attempts": []}

    def grant_scope(self, grant) -> None:
        self.grants.append(grant)

    def screenshot(self, path: pathlib.Path) -> bool:
        return False

    def retarget(self, app_name, window_title_pattern):
        return ("App", "Home")

    def target_text_for(self, ref):
        return ""

    def start_human_capture(self, on_action):
        on_action("human typed")

    def stop_human_capture(self):
        pass

    def inject_session_expiry(self):
        pass


def client(
    token: Optional[str] = None,
) -> Tuple[testclie.TestClient, FakeGatewaySurface]:
    """
    Serve a fresh fake gateway and return a client for it.
    """
    surface = FakeGatewaySurface()
    deps = app.DriverDeps(
        surface=surface,
        registry=registry.ToolRegistry(),
        redactor=redact.Redactor(),
        token=token,
    )
    return testclie.TestClient(app.create_driver_app(deps)), surface
