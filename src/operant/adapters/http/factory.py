"""
Choose the gateway transport for a run.

A remote driver daemon when ``driver.url`` is set (its process owns the
OS permissions), else the in-process macOS gateway. The macOS adapter is
imported lazily so the server process never loads xa11y.

Import as:

import operant.adapters.http.factory as factory
"""

from __future__ import annotations

import collections.abc
from typing import Any, Dict, List, Optional, Tuple, cast

import operant.domain.approval as approval
import operant.domain.models.actions as actions
import operant.domain.policy as dppolicy
import operant.domain.profile as profile
import operant.infra.settings as issettin
import operant.ports.surface as pssurfac

Event = dict[str, Any]
OnEvent = collections.abc.Callable[[Event], None]
OnDecision = collections.abc.Callable[
    [approval.PolicyDecision, actions.SurfaceAction], None
]
HealthTable = collections.abc.Callable[[], list[dict[str, Any]]]


def surface_for(
    *,
    app_name: str,
    window_title_pattern: str,
    policy: dppolicy.Policy,
    on_event: OnEvent,
    on_decision: OnDecision,
    settings: issettin.OperantSettings,
    fault_injection: Optional[profile.FaultInjection] = None,
) -> Tuple[pssurfac.Surface, HealthTable]:
    """
    Build the surface and a health-table callable for a run.

    :param app_name: Application to bind.
    :param window_title_pattern: Window title pattern.
    :param policy: Policy the guard enforces.
    :param on_event: Sink for gateway events.
    :param on_decision: Sink for policy decisions.
    :param settings: Driver URL, browser knowledge, and paths.
    :param fault_injection: Session-expiry config, when available.
    :return:``(surface, health_table)``.
    """
    driver = settings.driver
    if driver.url:
        # A remote daemon owns the OS permissions.
        token = (
            driver.auth_token.get_secret_value() if driver.auth_token else None
        )
        remote = _remote_surface(driver.url, token, on_event)
        result = (remote, remote.health_table)
    else:
        # Fall back to the in-process macOS gateway.
        result = _in_process_surface(
            app_name,
            window_title_pattern,
            policy,
            on_event,
            on_decision,
            settings,
            fault_injection,
        )
    return result


def _remote_surface(url: str, token: Optional[str], on_event: OnEvent) -> Any:
    """
    Build a remote gateway surface bound to the driver daemon.
    """
    import operant.adapters.http.remote_surface as remote_s

    surface = remote_s.RemoteGatewaySurface(url, token=token, on_event=on_event)
    return surface


def _in_process_surface(
    app_name: str,
    window_title_pattern: str,
    policy: dppolicy.Policy,
    on_event: OnEvent,
    on_decision: OnDecision,
    settings: issettin.OperantSettings,
    fault_injection: Optional[profile.FaultInjection],
) -> Tuple[pssurfac.Surface, HealthTable]:
    """
    Build the in-process macOS gateway surface and health table.
    """
    import operant.adapters.macos.setup as setup

    # Assemble the macOS gateway and its tool registry.
    surface, registry = setup.build_gateway_surface(
        app_name=app_name,
        window_title_pattern=window_title_pattern,
        policy=policy,
        on_event=on_event,
        on_decision=on_decision,
        paths=settings.paths,
        browser=settings.browser,
        fault_injection=fault_injection,
    )

    # Expose each tool's health as table rows.
    def health_table() -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for tool in registry.all():
            health = tool.health()
            rows.append(
                {
                    "name": tool.spec.name,
                    "serves": sorted(tool.spec.serves),
                    "status": health.status,
                    "reason": health.reason,
                    "permissions": list(tool.spec.permissions),
                }
            )
        return rows

    # Hand back the surface with its health-table callable.
    typed_surface = cast(pssurfac.Surface, surface)
    return typed_surface, health_table
