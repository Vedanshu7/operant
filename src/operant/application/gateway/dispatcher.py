"""
Dispatch an abstract action through its tool chain.

Fallback semantics: tools are tried in order; ``unavailable`` health
skips a tool up front; a ``failed`` or ``unsupported`` result falls
through to the next. An ``ok`` result the tool could not verify itself
is checked by the shared verifier - an unverified effect is a failure,
not a success (AX writes that report success and change nothing are the
cautionary case).

Every attempt is journaled, so the gateway learns at the moment of
action which tool works for which action on which surface.

Import as:

import operant.application.gateway.dispatcher as dispat
"""

from __future__ import annotations

import collections.abc
import dataclasses
from typing import Dict, List, Optional, Tuple

import operant.application.gateway.learner as gllearne
import operant.application.gateway.registry as grregist
import operant.domain.errors as errors
import operant.domain.models.actions as actions
import operant.domain.models.digest as mddigest
import operant.domain.models.tools as tools
import operant.ports.tool as pttool

Event = Dict[str, object]
Verifier = collections.abc.Callable[
    [actions.SurfaceAction, tools.ExecutionContext], Tuple[bool, str]
]
SignatureOf = collections.abc.Callable[
    [actions.SurfaceAction, Optional[mddigest.ScreenDigest]], str
]


# #############################################################################
# DispatchOutcome
# #############################################################################


@dataclasses.dataclass(frozen=True)
class DispatchOutcome:
    """
    The result of dispatching an action.

    :ivar tool: The tool that served the action.
    :ivar attempts: Every attempt made, in order.
    :ivar digest: Observation for observer actions.
    """

    tool: str
    attempts: Tuple[tools.Attempt, ...]
    digest: Optional[mddigest.ScreenDigest] = None


def _no_event(_event: Event) -> None:
    """
    Drop the event (default sink).
    """


# #############################################################################
# Dispatcher
# #############################################################################


@dataclasses.dataclass
class Dispatcher:
    """
    Run an action through its chain with fallback, verify, and learning.

    :ivar registry: Where tools are resolved.
    :ivar config: The chain configuration.
    :ivar on_event: Called with each journaled event.
    :ivar verifiers: Per-action-kind effect verifiers.
    :ivar learner: Reorders chains and records winners; optional.
    :ivar signature_of: Builds the learn signature from action and
        digest.
    """

    registry: grregist.ToolRegistry
    config: grregist.GatewayConfig
    on_event: collections.abc.Callable[[Event], None] = _no_event
    verifiers: Dict[str, Verifier] = dataclasses.field(default_factory=dict)
    learner: Optional[gllearne.ToolLearner] = None
    signature_of: Optional[SignatureOf] = None

    def dispatch(
        self,
        action: actions.SurfaceAction,
        ctx: tools.ExecutionContext,
    ) -> DispatchOutcome:
        """
        Execute ``action``, trying its chain until one tool succeeds.
        """
        kind = action.kind
        chain = self._ordered_chain(action, ctx)
        attempts: List[tools.Attempt] = []
        usable = self._usable_tools(action, chain, attempts)
        if not usable:
            names = [tool.spec.name for tool in chain]
            raise errors.NoToolAvailableError(
                kind,
                f'no usable tool for action kind "{kind}" (chain: {names})',
            )
        outcome = self._run_chain(action, ctx, usable, attempts)
        return outcome

    def _ordered_chain(
        self,
        action: actions.SurfaceAction,
        ctx: tools.ExecutionContext,
    ) -> List[pttool.Tool]:
        """
        Resolve the configured chain, learned winner first.
        """
        chain = self.registry.chain_for(action.kind, self.config)
        sig = self._signature(action, ctx)
        if self.learner is not None and sig is not None:
            # Learner available: float its recorded winner to the front.
            names = self.learner.order_chain(
                sig, [tool.spec.name for tool in chain]
            )
            ordered = [self.registry.get(name) for name in names]
        else:
            # No learner: keep the configured chain order.
            ordered = chain
        return ordered

    def _usable_tools(
        self,
        action: actions.SurfaceAction,
        chain: List[pttool.Tool],
        attempts: List[tools.Attempt],
    ) -> List[pttool.Tool]:
        """
        Filter the chain to tools that are healthy and safe to try.
        """
        usable: List[pttool.Tool] = []
        for tool in chain:
            health = tool.health()
            if health.status == "unavailable":
                # Tool reports itself down: skip it as unavailable.
                self._skip(
                    action, attempts, tool, "skipped_unavailable", health.reason
                )
            elif action.data_class != "none" and tool.spec.leaks_value:
                # Tool would leak a sensitive value: skip it.
                reason = (
                    f"would expose a {action.data_class} value "
                    "outside the target field"
                )
                self._skip(action, attempts, tool, "skipped_sensitive", reason)
            else:
                # Healthy and safe: keep it in the usable set.
                usable.append(tool)
        return usable

    def _run_chain(
        self,
        action: actions.SurfaceAction,
        ctx: tools.ExecutionContext,
        usable: List[pttool.Tool],
        attempts: List[tools.Attempt],
    ) -> DispatchOutcome:
        """
        Try each usable tool in order until one reports ``ok``.
        """
        sig = self._signature(action, ctx)
        for tool in usable:
            result = self._execute(tool, action, ctx)
            attempts.append(
                tools.Attempt(tool.spec.name, result.status, result.reason)
            )
            self._journal_action(action, tool, result)
            if result.status == "ok":
                self._record_winner(sig, action.kind, tool.spec.name)
                outcome = DispatchOutcome(
                    tool=tool.spec.name,
                    attempts=tuple(attempts),
                    digest=result.digest,
                )
                return outcome
        raise errors.AllToolsFailedError(action.kind, attempts)

    def _execute(
        self,
        tool: pttool.Tool,
        action: actions.SurfaceAction,
        ctx: tools.ExecutionContext,
    ) -> tools.ToolResult:
        """
        Run one tool, turning a crash into a failed result.
        """
        try:
            result = tool.execute(action, ctx)
        except Exception as err:
            # Failed attempt, not a dead run, so any exception is caught.
            outcome = tools.ToolResult(
                status="failed", reason=f"{type(err).__name__}: {err}"
            )
        else:
            verifier = self.verifiers.get(action.kind)
            if result.status == "ok" and not result.verified and verifier:
                # An unverified ok: confirm the effect actually landed.
                ok, observed = verifier(action, ctx)
                if ok:
                    # Effect confirmed: report ok as verified.
                    outcome = tools.ToolResult(
                        status="ok", verified=True, digest=result.digest
                    )
                else:
                    # Effect missing: turn the ok into a failure.
                    outcome = tools.ToolResult(
                        status="failed",
                        reason=f"effect not verified: {observed}",
                    )
            else:
                # Already verified or nothing to check: pass it through.
                outcome = result
        return outcome

    def _signature(
        self,
        action: actions.SurfaceAction,
        ctx: tools.ExecutionContext,
    ) -> Optional[str]:
        """
        Build the learn signature for this action, if configured.
        """
        if self.signature_of is None:
            sig = None
        else:
            sig = self.signature_of(action, ctx.digest)
        return sig

    def _record_winner(
        self, sig: Optional[str], kind: str, tool_name: str
    ) -> None:
        """
        Record the winning tool with the learner, if one is set.
        """
        if self.learner is None or sig is None:
            return
        if self.learner.record(sig, tool_name):
            self.on_event(
                {
                    "type": "gateway_learned",
                    "action": kind,
                    "tool": tool_name,
                    "signature": sig,
                    "reason": "recorded winning tool for this surface",
                }
            )

    def _skip(
        self,
        action: actions.SurfaceAction,
        attempts: List[tools.Attempt],
        tool: pttool.Tool,
        status: str,
        reason: str,
    ) -> None:
        """
        Record a skipped tool as an attempt and journals the skip.
        """
        name = tool.spec.name
        attempts.append(tools.Attempt(name, status, reason))
        self.on_event(
            {
                "type": "gateway_skip",
                "action": action.kind,
                "tool": name,
                "reason": reason,
            }
        )

    def _journal_action(
        self,
        action: actions.SurfaceAction,
        tool: pttool.Tool,
        result: tools.ToolResult,
    ) -> None:
        """
        Journals one executed attempt.
        """
        self.on_event(
            {
                "type": "gateway_action",
                "action": action.kind,
                "tool": tool.spec.name,
                "status": result.status,
                "reason": result.reason,
                "verified": result.verified,
                "target": action.target_text,
            }
        )
