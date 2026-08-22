"""
The driver daemon FastAPI app and its ``operant serve-driver`` entry.

Import as:

import operant.adapters.http.driver.app as daapp
"""

from __future__ import annotations

import dataclasses
import pathlib
import tempfile
import threading
from typing import Any, Dict, Optional, Union

import fastapi
import fastapi.responses as response
import uvicorn

import operant.adapters.http.common as common
import operant.application.gateway.registry as grregist
import operant.application.gateway.wire as wire
import operant.domain.approval as approval
import operant.domain.errors as errors
import operant.domain.models.actions as actions
import operant.domain.profile as dpprofil
import operant.domain.redaction as redact
import operant.helpers.logging as logging
import operant.infra.settings as issettin
import operant.ports.surface as pssurfac

_LOG = logging.get_logger(__name__)

_CAPTURE_UNAVAILABLE = "full UI capture is not available in this build"


# #############################################################################
# DriverDeps
# #############################################################################


@dataclasses.dataclass
class DriverDeps:
    """
    What the driver app is wired with.

    :ivar surface: The guarded macOS gateway surface.
    :ivar registry: Tool registry, for the health table.
    :ivar redactor: Masks secret values in the daemon's own logs.
    :ivar token: Bearer token every request must present; ``None``
        disables.
    """

    surface: pssurfac.Surface
    registry: grregist.ToolRegistry
    redactor: redact.Redactor
    token: Optional[str] = None
    lock: threading.Lock = dataclasses.field(default_factory=threading.Lock)


def create_driver_app(deps: DriverDeps) -> fastapi.FastAPI:
    """
    Build the driver daemon app with every route bearer-protected.
    """
    app = fastapi.FastAPI(title="Operant driver")
    common.install_error_handlers(app)
    guard = common.bearer_dependency(deps.token)
    router = fastapi.APIRouter(dependencies=[fastapi.Depends(guard)])
    capture: Dict[str, Any] = {"buffer": [], "active": False}
    _register_health(router, deps)
    _register_actions(router, deps)
    _register_capture(router, deps, capture)
    _register_control(router, deps)
    app.include_router(router)
    return app


def _register_health(router: fastapi.APIRouter, deps: DriverDeps) -> None:
    """
    Register the ``/health`` route on ``router``.
    """

    @router.get("/health")
    def health() -> Dict[str, Any]:
        tools = []
        for tool in deps.registry.all():
            report = tool.health()
            tools.append(
                {
                    "name": tool.spec.name,
                    "serves": sorted(tool.spec.serves),
                    "status": report.status,
                    "reason": report.reason,
                    "permissions": list(tool.spec.permissions),
                }
            )
        return {"protocol": wire.PROTOCOL_VERSION, "tools": tools}


def _register_actions(router: fastapi.APIRouter, deps: DriverDeps) -> None:
    """
    Register the observe, perform, and screenshot routes.
    """

    @router.post("/observe")
    def observe() -> Dict[str, Any]:
        with deps.lock:
            screen = deps.surface.snapshot()
        return {"digest": wire.digest_to_dict(screen)}

    @router.post("/perform", response_model=None)
    def perform(
        body: Dict[str, Any],
    ) -> Union[response.JSONResponse, Dict[str, Any]]:
        action = wire.action_from_dict(body["action"])
        _register_secret(deps, action)
        with deps.lock:
            try:
                outcome = deps.surface.perform(
                    action, approval=body.get("approval")
                )
            except errors.ApprovalRequiredError as need:
                return _approval_required(need)
            except errors.PolicyViolationError as violation:
                return response.JSONResponse(
                    status_code=403,
                    content={
                        "error": "policy_violation",
                        "decision": wire.decision_to_dict(violation.decision),
                    },
                )
            except errors.AllToolsFailedError as failed:
                return _all_tools_failed(failed)
            except (
                errors.NoToolAvailableError,
                KeyError,
                RuntimeError,
                TimeoutError,
            ) as err:
                return response.JSONResponse(
                    status_code=500, content={"error": str(err)}
                )
        return {"ok": True, **(outcome if isinstance(outcome, dict) else {})}

    @router.get("/screenshot", response_model=None)
    def screenshot() -> Union[response.FileResponse, response.JSONResponse]:
        path = pathlib.Path(tempfile.mkdtemp()) / "shot.png"
        with deps.lock:
            try:
                deps.surface.screenshot(path)
            # Report the reason to the client.
            except Exception as err:
                return response.JSONResponse(
                    status_code=404, content={"error": str(err)}
                )
        if path.exists() and path.stat().st_size > 0:
            return response.FileResponse(path, media_type="image/png")
        return response.JSONResponse(
            status_code=404, content={"error": "screenshot unavailable"}
        )


def _register_secret(deps: DriverDeps, action: actions.SurfaceAction) -> None:
    """
    Register a secret-reference fill's value before it can be logged.
    """
    if action.secret_ref and action.value:
        deps.redactor.add_secret(action.value)


def _approval_required(
    need: errors.ApprovalRequiredError,
) -> response.JSONResponse:
    """
    Render an approval-required 428 response.
    """
    # 428 Precondition Required: the caller obtains a human's approval and
    # retries with the nonce. The value never leaves the daemon.
    rendered = response.JSONResponse(
        status_code=428,
        content={
            "error": "approval_required",
            "nonce": need.nonce,
            "request": wire.approval_request_to_dict(need.request),
        },
    )
    return rendered


def _all_tools_failed(
    failed: errors.AllToolsFailedError,
) -> response.JSONResponse:
    """
    Render an all-tools-failed 502 response.
    """
    rendered = response.JSONResponse(
        status_code=502,
        content={
            "error": "all_tools_failed",
            "attempts": [
                {"tool": a.tool, "status": a.status, "reason": a.reason}
                for a in failed.attempts
            ],
        },
    )
    return rendered


def _register_capture(
    router: fastapi.APIRouter, deps: DriverDeps, capture: Dict[str, Any]
) -> None:
    """
    Register the human-capture and session-capture routes.
    """

    @router.post("/capture/start")
    def capture_start() -> Dict[str, Any]:
        capture["buffer"] = []
        capture["active"] = True
        deps.surface.start_human_capture(capture["buffer"].append)
        return {"ok": True}

    @router.post("/capture/stop")
    def capture_stop() -> Dict[str, Any]:
        deps.surface.stop_human_capture()
        capture["active"] = False
        return {"ok": True}

    @router.get("/capture/actions")
    def capture_actions() -> Dict[str, Any]:
        return {"actions": list(capture["buffer"])}

    @router.post("/capture/session/start", response_model=None)
    def capture_session_start(
        body: Dict[str, Any],
    ) -> response.JSONResponse:
        # Full screen+input recording needs the optional capture extra, not
        # yet wired here; human-action capture above is what interventions
        # rely on.
        return response.JSONResponse(
            status_code=503, content={"error": _CAPTURE_UNAVAILABLE}
        )

    @router.post("/capture/session/stop")
    def capture_session_stop() -> Dict[str, Any]:
        return {"ok": True, "dir": None, "summary": {}}


def _register_control(router: fastapi.APIRouter, deps: DriverDeps) -> None:
    """
    Register the retarget, policy-grant, and inject-fault routes.
    """

    @router.post("/retarget")
    def retarget(body: Dict[str, Any]) -> Dict[str, Any]:
        with deps.lock:
            previous = deps.surface.retarget(
                body["app_name"], body["window_title_pattern"]
            )
        return {"previous": list(previous)}

    @router.post("/policy/grant")
    def policy_grant(body: Dict[str, Any]) -> Dict[str, Any]:
        grant = approval.ScopeGrant.model_validate(body)
        with deps.lock:
            deps.surface.grant_scope(grant)
        _LOG.info(
            "scope granted (%s): %s - %s",
            grant.kind,
            grant.pattern,
            grant.reason,
        )
        return {"ok": True}

    @router.post("/inject-fault")
    def inject_fault() -> Dict[str, Any]:
        with deps.lock:
            deps.surface.inject_session_expiry()
        return {"ok": True}


def build_daemon_redactor(
    profile: dpprofil.AppProfile,
    settings: issettin.OperantSettings,
) -> redact.Redactor:
    """
    Seed a redactor with every tenant secret the profile references.
    """
    import operant.adapters.secrets.factory as factory

    # Load the configured secret store.
    store = factory.secret_store(settings.secrets)
    redactor = redact.redactor_from_env({})
    import operant.application.secrets as secrets

    # Seed the redactor from each tenant's referenced secrets.
    for tenant in profile.tenants.values():
        secrets.SecretResolver(tenant, store, redactor).resolve_available()
    return redactor


def serve_driver(
    profile: dpprofil.AppProfile,
    settings: issettin.OperantSettings,
) -> None:
    """
    Build and run the driver daemon for ``profile``.
    """
    import operant.adapters.macos.setup as setup

    # Build the redactor before anything can log a secret.
    redactor = build_daemon_redactor(profile, settings)

    # Log every gateway event with secret values redacted.
    def on_event(event: Dict[str, Any]) -> None:
        _LOG.info(
            "%s tool=%s action=%s status=%s %s",
            event.get("type"),
            event.get("tool"),
            event.get("action"),
            event.get("status", ""),
            redactor.redact(str(event.get("reason", ""))),
        )

    # Log each policy decision with its reason redacted.
    def on_decision(
        decision: approval.PolicyDecision,
        action: actions.SurfaceAction,
    ) -> None:
        _LOG.info(
            "policy %s %s (%s): %s",
            decision.verdict,
            action.kind,
            decision.risk,
            redactor.redact(decision.reason),
        )

    # Assemble the guarded gateway for this profile.
    surface, registry = setup.build_gateway_surface(
        app_name=profile.app_name,
        window_title_pattern=profile.window_title_pattern,
        policy=profile.policy,
        on_event=on_event,
        on_decision=on_decision,
        paths=settings.paths,
        browser=settings.browser,
        fault_injection=profile.fault_injection,
    )
    token = (
        settings.driver.auth_token.get_secret_value()
        if settings.driver.auth_token
        else None
    )
    app = create_driver_app(
        DriverDeps(
            surface=surface,
            registry=registry,
            redactor=redactor,
            token=token,
        )
    )
    _LOG.info(
        "operant driver daemon on http://%s:%d (profile: %s)",
        settings.driver.host,
        settings.driver.port,
        profile.vendor_id,
    )
    _LOG.info(
        "this process holds the OS automation permissions - leave it running"
    )
    uvicorn.run(
        app,
        host=settings.driver.host,
        port=settings.driver.port,
        log_level="warning",
    )
