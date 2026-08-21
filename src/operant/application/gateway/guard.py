"""
The policy choke point in front of the dispatcher.

Observation is read-only and window-scoped by construction, so it is not
subject to the action allowlist; every actuation is. Approval is
enforced here, in the trusted process: a ``needs_approval`` decision
never dispatches. It raises ``ApprovalRequiredError`` with a single-use
nonce bound to the request's fingerprint; only a retry presenting that
nonce for the same question may proceed. Who answers the question is the
caller's business.

Import as:

import operant.application.gateway.guard as guard
"""

from __future__ import annotations

import collections.abc
import dataclasses
from typing import Dict, List, Optional, Tuple

import operant.application.gateway.dispatcher as dispat
import operant.domain.approval as daapprov
import operant.domain.errors as errors
import operant.domain.models.actions as actions
import operant.domain.models.digest as digest
import operant.domain.models.tools as tools
import operant.domain.policy as policy
import operant.helpers.ids as ids
import operant.helpers.time as time

OnDecision = collections.abc.Callable[
    [daapprov.PolicyDecision, actions.SurfaceAction], None
]


# #############################################################################
# GuardedGateway
# #############################################################################


class GuardedGateway:
    """
    Wrap a dispatcher with the policy gate and scope grants.

    :ivar grants: Human-approved scope widenings for this session;
        enforcement stays here, never in the caller.
    """

    def __init__(
        self,
        dispatcher: dispat.Dispatcher,
        app_policy: policy.Policy,
        *,
        on_decision: OnDecision,
        nonce_ttl_s: float = 600.0,
    ) -> None:
        self._dispatcher = dispatcher
        self._policy = app_policy
        self._on_decision = on_decision
        self._nonce_ttl_s = nonce_ttl_s
        self._last_digest: Optional[digest.ScreenDigest] = None
        self.grants: List[daapprov.ScopeGrant] = []
        self._pending: Dict[str, Tuple[str, float]] = {}

    def grant(self, grant: daapprov.ScopeGrant) -> None:
        """
        Record a human-approved scope widening for this session.
        """
        self.grants.append(grant)

    @property
    def last_digest(self) -> Optional[digest.ScreenDigest]:
        """
        The most recent observation, or ``None`` before the first.
        """
        return self._last_digest

    def control_for(self, ref: Optional[str]) -> Optional[digest.Control]:
        """
        Return the control with ``ref`` from the last observation.
        """
        if ref is None or self._last_digest is None:
            control = None
        else:
            control = next(
                (c for c in self._last_digest.controls if c.ref == ref), None
            )
        return control

    def target_text_for(self, ref: Optional[str]) -> str:
        """
        Return the human-readable text of the control ``ref``.
        """
        control = self.control_for(ref)
        if control is None:
            text = ""
        else:
            text = " | ".join(x for x in (control.name, control.label) if x)
        return text

    def observe(self, ctx: tools.ExecutionContext) -> digest.ScreenDigest:
        """
        Observe the window through the observer tool chain.
        """
        outcome = self._dispatcher.dispatch(
            actions.SurfaceAction(kind="observe"), ctx
        )
        if outcome.digest is None:
            raise errors.SurfaceError("observer tool returned no digest")
        screen = outcome.digest
        self._last_digest = screen
        ctx.digest = screen
        return screen

    def perform(
        self,
        action: actions.SurfaceAction,
        ctx: tools.ExecutionContext,
        *,
        approval: Optional[str] = None,
    ) -> dispat.DispatchOutcome:
        """
        Evaluate ``action`` against policy, then dispatches it.
        """
        if action.ref is not None and not action.target_text:
            action = dataclasses.replace(
                action, target_text=self.target_text_for(action.ref)
            )
        decision = self._evaluate(action)
        if decision.verdict == "needs_approval":
            decision = self._gate(action, decision, approval)
        self._on_decision(decision, action)
        if decision.verdict == "deny":
            raise errors.PolicyViolationError(decision)
        outcome = self._dispatcher.dispatch(action, ctx)
        return outcome

    def _evaluate(self, action: actions.SurfaceAction) -> daapprov.PolicyDecision:
        """
        Evaluate the action against policy for the current app.
        """
        app = (
            self._last_digest.app
            if self._last_digest is not None
            else (action.app or "")
        )
        decision = policy.evaluate_action(
            self._policy,
            action,
            grants=self.grants,
            digest=self._last_digest,
            control=self.control_for(action.ref),
            app=app,
        )
        return decision

    def _gate(
        self,
        action: actions.SurfaceAction,
        decision: daapprov.PolicyDecision,
        approval: Optional[str],
    ) -> daapprov.PolicyDecision:
        """
        Gate a needs-approval decision on a matching nonce.
        """
        request = decision.approval
        if request is None:
            raise errors.PolicyViolationError(decision)
        if self._consume(approval, request.fingerprint):
            approved = daapprov.PolicyDecision(
                verdict="allow",
                risk=decision.risk,
                reason=(f"approved by human ({request.kind}): {request.summary}"),
                approval=request,
            )
            return approved
        self._on_decision(decision, action)
        nonce = ids.nonce()
        self._pending[nonce] = (
            request.fingerprint,
            time.monotonic() + self._nonce_ttl_s,
        )
        raise errors.ApprovalRequiredError(request, nonce, action)

    def _consume(self, nonce: Optional[str], fingerprint: str) -> bool:
        """
        Consume a pending nonce matching the fingerprint.
        """
        now = time.monotonic()
        self._pending = {n: v for n, v in self._pending.items() if v[1] > now}
        if nonce is None:
            valid = False
        else:
            pending = self._pending.pop(nonce, None)
            valid = pending is not None and pending[0] == fingerprint
        return valid
