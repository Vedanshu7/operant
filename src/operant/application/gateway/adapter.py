"""
The in-process gateway presented as a ``Surface``.

Callers keep calling ``snapshot`` / ``perform``; underneath, every
action goes through the policy guard and the tool chains. The session is
opaque to this layer - a macOS ``WindowSession`` today, another OS's
session tomorrow.

Import as:

import operant.application.gateway.adapter as adapter
"""

from __future__ import annotations

import collections.abc
import pathlib
from typing import Any, Dict, Optional, Tuple

import operant.application.gateway.guard as guard
import operant.domain.approval as daapprov
import operant.domain.models.actions as actions
import operant.domain.models.digest as digest
import operant.domain.models.tools as tools

# #############################################################################
# GatewaySurface
# #############################################################################


class GatewaySurface:
    """
    Implements ``operant.ports.surface.Surface`` over the guarded gateway.

    ``session`` is opaque here - a bound window session typed by the
    OS- specific tools and session implementation.
    """

    def __init__(self, gateway: guard.GuardedGateway, session: Any) -> None:
        self._gateway = gateway
        self._session = session

    def snapshot(self) -> digest.ScreenDigest:
        """
        Observe the bound window through the guard.
        """
        observed = self._gateway.observe(
            tools.ExecutionContext(session=self._session)
        )
        return observed

    def perform(
        self, action: actions.SurfaceAction, *, approval: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Run one action; returns the tool and attempts as evidence.
        """
        ctx = tools.ExecutionContext(
            session=self._session, digest=self._gateway.last_digest
        )
        if action.ref is not None:
            ctx.target = self._session.element_for(action.ref)
        outcome = self._gateway.perform(action, ctx, approval=approval)
        evidence = {
            "tool": outcome.tool,
            "attempts": [
                {"tool": a.tool, "status": a.status, "reason": a.reason}
                for a in outcome.attempts
            ],
        }
        return evidence

    def retarget(
        self, app_name: str, window_title_pattern: str
    ) -> Tuple[str, str]:
        """
        Rebinds the session to another app window.
        """
        previous: Tuple[str, str] = self._session.retarget(
            app_name, window_title_pattern
        )
        return previous

    def grant_scope(self, grant: daapprov.ScopeGrant) -> None:
        """
        Record a human-approved scope grant on the guard.
        """
        self._gateway.grant(grant)

    def target_text_for(self, ref: Optional[str]) -> str:
        """
        Return the human-readable text of the control ``ref``.
        """
        text = self._gateway.target_text_for(ref)
        return text

    def screenshot(self, path: pathlib.Path) -> bool:
        """
        Write a PNG of the bound window to ``path``.
        """
        wrote: bool = self._session.screenshot(str(path))
        return wrote

    def start_human_capture(
        self, on_action: collections.abc.Callable[[str], None]
    ) -> None:
        """
        Start streaming the human's actions during a hand-off.
        """
        self._session.start_human_capture(on_action)

    def stop_human_capture(self) -> None:
        """
        Stop the human-action stream.
        """
        self._session.stop_human_capture()

    def start_capture(
        self,
        out_dir: pathlib.Path,
        task: str,
        window: Optional[collections.abc.Mapping[str, Optional[str]]],
        *,
        video: bool = True,
    ) -> bool:
        """
        Full UI capture is hosted by the daemon; absent in-process.
        """
        return False

    def stop_capture(self) -> collections.abc.Mapping[str, Any]:
        """
        No-op in-process; returns an empty summary.
        """
        summary: collections.abc.Mapping[str, Any] = {}
        return summary

    def inject_session_expiry(self) -> None:
        """
        Force a session-expiry condition for fault-injection tests.
        """
        self._session.inject_session_expiry()

    def close(self) -> None:
        """
        Release the underlying session.
        """
        self._session.close()
