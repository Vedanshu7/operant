"""
The driver daemon over ASGI: status-code mapping, bearer, and redaction.
"""

import pathlib
from typing import List, Optional, Tuple

import fastapi.testclient as testclie

import operant.adapters.http.driver.app as app
import operant.application.gateway.registry as registry
import operant.application.gateway.wire as wire
import operant.domain.approval as daapprov
import operant.domain.errors as errors
import operant.domain.models.actions as actions
import operant.domain.models.digest as digest
import operant.domain.redaction as redact

# #############################################################################
# _FakeSurface
# #############################################################################


class _FakeSurface:

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


def _client(
    token: Optional[str] = None,
) -> Tuple[testclie.TestClient, _FakeSurface]:
    surface = _FakeSurface()
    deps = app.DriverDeps(
        surface=surface,
        registry=registry.ToolRegistry(),
        redactor=redact.Redactor(),
        token=token,
    )
    return testclie.TestClient(app.create_driver_app(deps)), surface


def _perform_body(action: actions.SurfaceAction) -> dict:
    return {"action": wire.action_to_dict(action), "approval": None}


def test_health_reports_protocol() -> None:
    client, _ = _client()
    body = client.get("/health").json()
    assert body["protocol"] == wire.PROTOCOL_VERSION


def test_perform_maps_status_codes() -> None:
    client, _ = _client()
    ok = client.post(
        "/perform",
        json=_perform_body(actions.SurfaceAction(kind="click", ref="c0")),
    )
    assert ok.status_code == 200 and ok.json()["ok"] is True
    gated = client.post(
        "/perform",
        json=_perform_body(
            actions.SurfaceAction(kind="click", ref="c0", step="mutating")
        ),
    )
    assert gated.status_code == 428
    assert gated.json()["nonce"] == "nonce-1"
    denied = client.post(
        "/perform",
        json=_perform_body(
            actions.SurfaceAction(kind="click", ref="c0", step="denied")
        ),
    )
    assert denied.status_code == 403
    assert denied.json()["decision"]["reason"] == "not allowed"


def test_secret_ref_fill_value_is_registered_with_the_redactor() -> None:
    surface = _FakeSurface()
    redactor = redact.Redactor()
    deps = app.DriverDeps(
        surface=surface,
        registry=registry.ToolRegistry(),
        redactor=redactor,
        token=None,
    )
    client = testclie.TestClient(app.create_driver_app(deps))
    action = actions.SurfaceAction(
        kind="fill",
        ref="pw",
        value="hunter2-pw",
        data_class="credential",
        secret_ref="password",
    )
    client.post("/perform", json=_perform_body(action))
    # The daemon learned the value before performing, so its logs mask it.
    assert redactor.redact("typed hunter2-pw") == "typed [REDACTED]"
    assert surface.performed[-1].value == "hunter2-pw"


def test_policy_grant_and_capture_actions() -> None:
    client, surface = _client()
    grant = daapprov.ScopeGrant(kind="app", pattern="Notes")
    assert (
        client.post(
            "/policy/grant", json=grant.model_dump(mode="json")
        ).status_code
        == 200
    )
    assert [g.pattern for g in surface.grants] == ["Notes"]
    client.post("/capture/start")
    actions_body = client.get("/capture/actions").json()
    assert actions_body["actions"] == ["human typed"]


def test_full_capture_session_is_unavailable() -> None:
    client, _ = _client()
    started = client.post("/capture/session/start", json={"out_dir": "/tmp/x"})
    assert started.status_code == 503


def test_bearer_token_is_enforced() -> None:
    client, _ = _client(token="s3cret")
    assert client.get("/health").status_code == 401
    ok = client.get("/health", headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200
