"""
Scripted surfaces for replay and discovery tests.

``GatedFakeSurface`` enforces the policy and the approval nonce protocol
exactly like the real guard, so tests exercise the same gate the live
gateway applies. ``TitledSurface`` scripts a sequence of window titles
for pure engine tests that need no policy.
"""

from __future__ import annotations

import dataclasses
import pathlib
from typing import Dict, List, Optional, Tuple

import operant.domain.approval as daapprov
import operant.domain.errors as errors
import operant.domain.models.actions as actions
import operant.domain.models.digest as digest
import operant.domain.policy as policy

# #############################################################################
# GatedFakeSurface
# #############################################################################


class GatedFakeSurface:
    """
    A surface that runs the real policy gate over scripted screens.
    """

    def __init__(self, app_policy: policy.Policy) -> None:
        self.policy = app_policy
        self.grants: List[daapprov.ScopeGrant] = []
        self.performed: List[actions.SurfaceAction] = []
        self.binding: Optional[Tuple[str, str]] = None
        self._pending: Dict[str, str] = {}
        self._seq = 0

    def snapshot(self) -> digest.ScreenDigest:
        """
        Script the screen (subclasses override).
        """
        raise NotImplementedError

    def apply(self, action: actions.SurfaceAction) -> None:
        """
        Subclass hook: advance the screen after an allowed action.
        """

    def perform(
        self, action: actions.SurfaceAction, *, approval: Optional[str] = None
    ) -> object:
        screen = self._digest_or_none()
        control = None
        if screen is not None and action.ref is not None:
            control = next(
                (c for c in screen.controls if c.ref == action.ref), None
            )
        if control is not None and not action.target_text:
            action = dataclasses.replace(
                action,
                target_text=" | ".join(
                    x for x in (control.name, control.label) if x
                ),
            )
        decision = policy.evaluate_action(
            self.policy,
            action,
            grants=self.grants,
            digest=screen,
            control=control,
            app=screen.app if screen is not None else (action.app or ""),
        )
        if decision.verdict == "deny":
            raise errors.PolicyViolationError(decision)
        if decision.verdict == "needs_approval":
            request = decision.approval
            if request is None:
                raise errors.PolicyViolationError(decision)
            granted = self._pending.pop(approval, None) if approval else None
            if granted != request.fingerprint:
                self._seq += 1
                nonce = f"nonce-{self._seq}"
                self._pending[nonce] = request.fingerprint
                raise errors.ApprovalRequiredError(request, nonce, action)
        self.performed.append(action)
        self.apply(action)
        return None

    def grant_scope(self, grant: daapprov.ScopeGrant) -> None:
        self.grants.append(grant)

    def retarget(self, app_name: str, pattern: str) -> Tuple[str, str]:
        prev = self.binding or ("", "")
        self.binding = (app_name, pattern)
        return prev

    def target_text_for(self, ref: Optional[str]) -> str:
        screen = self._digest_or_none()
        if screen is None or ref is None:
            return ""
        control = next((c for c in screen.controls if c.ref == ref), None)
        if control is None:
            return ""
        return " | ".join(x for x in (control.name, control.label) if x)

    def screenshot(self, path: pathlib.Path) -> bool:
        return False

    def _digest_or_none(self) -> Optional[digest.ScreenDigest]:
        try:
            return self.snapshot()
        except Exception:  # no window bound yet
            return None


# #############################################################################
# TitledSurface
# #############################################################################


class TitledSurface:
    """
    Each successful perform advances to the next scripted window title.
    """

    def __init__(
        self, titles: List[str], texts: Optional[Dict[str, str]] = None
    ) -> None:
        self.title = titles[0]
        self._pending = titles[1:]
        self._texts = texts or {}
        self.performed: List[actions.SurfaceAction] = []

    def controls_for(self, title: str) -> Tuple[digest.Control, ...]:
        """
        Subclass hook: the controls visible on ``title``.
        """
        return ()

    def snapshot(self) -> digest.ScreenDigest:
        return digest.ScreenDigest(
            app="app",
            window_title=self.title,
            text=self._texts.get(self.title, self.title),
            controls=self.controls_for(self.title),
        )

    def perform(
        self, action: actions.SurfaceAction, *, approval: Optional[str] = None
    ) -> object:
        self.performed.append(action)
        if self._pending:
            self.title = self._pending.pop(0)
        return None

    def target_text_for(self, ref: Optional[str]) -> str:
        return ""

    def screenshot(self, path: pathlib.Path) -> bool:
        return False
