"""
The driver daemon over ASGI: status-code mapping, bearer, and redaction.
"""

import fastapi.testclient as testclie

import operant.adapters.http.driver.app as app
import operant.application.gateway.registry as registry
import operant.application.gateway.wire as wire
import operant.domain.approval as daapprov
import operant.domain.models.actions as actions
import operant.domain.redaction as redact
import tests.support.driver as driver


def _perform_body(action: actions.SurfaceAction) -> dict:
    return {"action": wire.action_to_dict(action), "approval": None}


def test_health_reports_protocol() -> None:
    client, _ = driver.client()
    body = client.get("/health").json()
    assert body["protocol"] == wire.PROTOCOL_VERSION


def test_perform_maps_status_codes() -> None:
    client, _ = driver.client()
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
    surface = driver.FakeGatewaySurface()
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
    client, surface = driver.client()
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


def test_bearer_token_is_enforced() -> None:
    client, _ = driver.client(token="s3cret")
    assert client.get("/health").status_code == 401
    ok = client.get("/health", headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200
