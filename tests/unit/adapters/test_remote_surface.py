"""
The remote surface speaks the driver protocol against the real daemon app.
"""

from __future__ import annotations

from typing import Dict, List

import httpx
import pytest

import operant.adapters.http.remote_surface as remote
import operant.domain.approval as daapprov
import operant.domain.errors as errors
import operant.domain.models.actions as actions
import tests.support.driver as driver


def _remote(
    events: List[Dict[str, object]],
) -> tuple[remote.RemoteGatewaySurface, driver.FakeGatewaySurface]:
    client, surface = driver.client()
    built = remote.RemoteGatewaySurface(
        "http://testserver", client=client, on_event=events.append
    )
    return built, surface


def test_observe_retarget_and_grant_round_trip() -> None:
    surface_remote, surface = _remote([])
    assert surface_remote.snapshot().window_title == "Home"
    assert surface_remote.retarget("App", "Home") == ("App", "Home")
    grant = daapprov.ScopeGrant(kind="app", pattern="Notes", reason="operator")
    surface_remote.grant_scope(grant)
    assert surface.grants == [grant]


def test_perform_journals_the_tool_that_served_it() -> None:
    events: List[Dict[str, object]] = []
    surface_remote, surface = _remote(events)
    surface_remote.perform(actions.SurfaceAction(kind="click", ref="c0"))
    assert surface.performed[0].kind == "click"
    assert events == [
        {
            "type": "gateway_action",
            "action": "click",
            "tool": "ax-action",
            "status": "ok",
        }
    ]


def test_gated_and_denied_actions_raise_the_domain_errors() -> None:
    surface_remote, _ = _remote([])
    with pytest.raises(errors.ApprovalRequiredError) as gated:
        surface_remote.perform(
            actions.SurfaceAction(kind="click", ref="c0", step="mutating")
        )
    assert gated.value.nonce == "nonce-1"
    with pytest.raises(errors.PolicyViolationError) as denied:
        surface_remote.perform(
            actions.SurfaceAction(kind="click", ref="c0", step="denied")
        )
    assert denied.value.decision.reason == "not allowed"


def test_a_missing_screenshot_is_a_surface_error(tmp_path) -> None:
    surface_remote, _ = _remote([])
    with pytest.raises(errors.SurfaceError):
        surface_remote.screenshot(tmp_path / "shot.png")


def test_a_daemon_on_another_protocol_is_refused() -> None:
    def old_daemon(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "protocol": "0"})

    client = httpx.Client(
        base_url="http://testserver", transport=httpx.MockTransport(old_daemon)
    )
    with pytest.raises(errors.DriverError):
        remote.RemoteGatewaySurface("http://testserver", client=client)
