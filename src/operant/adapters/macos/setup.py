"""
Assemble the macOS gateway: session, tool set, chains, verifiers, guard.

The fill and select verifiers re-observe to get a fresh element handle
(Chrome regenerates a web field's accessibility node after a write, so
the handle captured at resolve time reads empty even though the field
holds the text) and, for non-secret fills, accept screen-level text
evidence.

Import as:

import operant.adapters.macos.setup as setup
"""

from __future__ import annotations

import collections.abc
import pathlib
import time
from typing import Optional, Tuple

import operant.adapters.macos.session as mssessio
import operant.adapters.macos.tools as tools
import operant.adapters.macos.tools.observe as observe
import operant.application.gateway.adapter as adapter
import operant.application.gateway.dispatcher as dispat
import operant.application.gateway.guard as guard
import operant.application.gateway.learner as gllearne
import operant.application.gateway.registry as grregist
import operant.domain.approval as approval
import operant.domain.models.actions as actions
import operant.domain.models.digest as digest
import operant.domain.models.tools as mttools
import operant.domain.policy as dppolicy
import operant.domain.profile as profile
import operant.domain.sensitivity as sensv
import operant.infra.repositories.learned_tools as learned_
import operant.infra.settings as settings

Event = dict[str, object]
OnEvent = collections.abc.Callable[[Event], None]
OnDecision = collections.abc.Callable[
    [approval.PolicyDecision, actions.SurfaceAction], None
]

_VERIFY_TIMEOUT_S = 3.0


def build_gateway_surface(
    *,
    app_name: str,
    window_title_pattern: str,
    policy: dppolicy.Policy,
    on_event: OnEvent,
    on_decision: OnDecision,
    paths: settings.PathsSettings,
    browser: settings.BrowserSettings,
    fault_injection: Optional[profile.FaultInjection] = None,
) -> Tuple[adapter.GatewaySurface, grregist.ToolRegistry]:
    """
    Wire a policy-guarded macOS gateway surface.

    :param app_name: Application to bind.
    :param window_title_pattern: Window title pattern.
    :param policy: Policy the guard enforces.
    :param on_event: Sink for journaled gateway events.
    :param on_decision: Sink for policy decisions.
    :param paths: Where the gateway policy and learned tools live.
    :param browser: Browser knowledge for the launcher.
    :param fault_injection: Session-expiry fault config, when available.
    :return:``(surface, registry)``.
    """
    session = mssessio.WindowSession(
        app_name, window_title_pattern, fault_injection
    )
    registry = _build_registry(session, browser, paths.chrome_profile_dir)
    config = grregist.load_gateway_config(paths.gateway_policy)
    registry.validate(config)
    learner = gllearne.ToolLearner(
        learned_.LearnedToolsStore(paths.learned_tools)
    )

    # Key each action by app and window for the tool learner.
    def signature_of(
        action: actions.SurfaceAction, screen: Optional[digest.ScreenDigest]
    ) -> str:
        return gllearne.signature(
            action, app_name, screen.window_title if screen else ""
        )

    # Assemble the dispatcher, guard, and surface.
    engine = dispat.Dispatcher(
        registry,
        config,
        on_event=on_event,
        verifiers={"fill": _fill_verifier, "select": _select_verifier},
        learner=learner,
        signature_of=signature_of,
    )
    gateway = guard.GuardedGateway(engine, policy, on_decision=on_decision)
    surface = adapter.GatewaySurface(gateway, session)
    return surface, registry


def _build_registry(
    session: mssessio.WindowSession,
    browser: settings.BrowserSettings,
    chrome_profile_dir: pathlib.Path,
) -> grregist.ToolRegistry:
    """
    Register every macOS tool, launcher first.
    """
    registry = grregist.ToolRegistry()
    registry.register(tools.AppLauncher(session, browser, chrome_profile_dir))
    for tool in (
        tools.Xa11yDigestObserver(session),
        tools.AxActionTool(session),
        tools.AppleScriptKeysTool(session),
        tools.ClipboardPasteTool(session),
        tools.OsInputTool(session),
        tools.SystemEventsPressTool(session),
        tools.AxSelectTool(session),
        tools.SeSelectTool(session),
        tools.AxScrollTool(session),
        tools.OsInputScrollTool(session),
        tools.CoordinateClickTool(session),
    ):
        registry.register(tool)
    return registry


def _fill_verifier(
    action: actions.SurfaceAction, ctx: mttools.ExecutionContext
) -> Tuple[bool, str]:
    """
    Re-observe until the fill is read back or the text shows on screen.
    """
    if ctx.target is None or action.ref is None:
        return False, "no target element to verify against"
    observer = observe.Xa11yDigestObserver(ctx.session)
    expected = action.value or ""
    deadline = time.monotonic() + _VERIFY_TIMEOUT_S
    last = ""
    while time.monotonic() < deadline:
        result = observer.execute(actions.SurfaceAction(kind="observe"), ctx)
        fresh = ctx.session.refs.get(action.ref)
        if fresh is not None:
            got = fresh.value or ""
            if _value_matches(got, expected):
                return True, _settled(action, got)
            last = got
        if _text_visible(expected, result):
            return True, "(text visible on screen)"
        time.sleep(0.2)
    return False, _verify_reason(action, last, expected)


def _select_verifier(
    action: actions.SurfaceAction, ctx: mttools.ExecutionContext
) -> Tuple[bool, str]:
    """
    Re-observe until the selected option reads back on the control.
    """
    if ctx.target is None or action.ref is None:
        return False, "no target element to verify against"
    observer = observe.Xa11yDigestObserver(ctx.session)
    expected = (action.option or "").strip().lower()
    deadline = time.monotonic() + _VERIFY_TIMEOUT_S
    last = ""
    while time.monotonic() < deadline:
        observer.execute(actions.SurfaceAction(kind="observe"), ctx)
        fresh = ctx.session.refs.get(action.ref)
        if fresh is not None:
            got = (fresh.value or "").strip()
            if got and (got.lower() == expected or expected in got.lower()):
                return True, _settled(action, got)
            last = got
        time.sleep(0.2)
    return False, _verify_reason(action, last, expected)


def _text_visible(expected: str, result: mttools.ToolResult) -> bool:
    """
    Report whether the expected text shows anywhere on screen.
    """
    # Native rich-text areas (Notes body) never read back via AXValue, but
    # the text visibly landing on screen IS the effect. Masked fields never
    # show their value, so secrets keep the strict read-back path.
    if not expected or result.digest is None:
        visible = False
    else:
        visible = expected in result.digest.text or any(
            c.value and expected in c.value for c in result.digest.controls
        )
    return visible


def _value_matches(got: str, expected: str) -> bool:
    """
    Report whether the read-back value matches, allowing masking.
    """
    if not expected:
        # No value expected: only an empty read-back matches.
        matches = got == ""
    elif got == expected:
        # An exact read-back matches.
        matches = True
    else:
        # Masked field: right length, entirely mask glyphs.
        matches = (
            len(got) == len(expected)
            and got != ""
            and all(ch in sensv.MASK_CHARS for ch in got)
        )
    return matches


def _verify_reason(
    action: actions.SurfaceAction, last: str, expected: str
) -> str:
    """
    Describe a failed read-back; sensitive values name lengths only.
    """
    if action.data_class != "none":
        # Sensitive value: report lengths only, never the text.
        reason = (
            f"value mismatch (read back {len(last)} chars, "
            f"expected {len(expected)})"
        )
    else:
        # Non-sensitive: show the actual read-back.
        reason = f"value is {last!r}"
    return reason


def _settled(action: actions.SurfaceAction, got: str) -> str:
    """
    Return a settle marker for sensitive data, else the value.
    """
    settled = "(settled)" if action.data_class != "none" else got
    return settled
