"""Approval vocabulary: the questions a policy puts to a human.

Provides the approval-related models shared by the policy evaluator,
the approval loop, and the HTTP layer: what kinds of approval exist,
how a policy configures them, the coarse scope grants a human can make,
the request put to a human, the recorded answer, and the three-state
policy decision that carries a request. Nothing here contains a typed
value; humans see a value's class and length only.

Typical usage example:

  decision = evaluate_action(policy, action)
  if decision.approval is not None:
      key = decision.approval.fingerprint

Import as:

import operant.domain.approval as approval
"""

from __future__ import annotations

import dataclasses
import hashlib
from typing import Dict, List, Literal, Optional, Tuple

import pydantic

import operant.domain.models.actions as actions

Risk = Literal["safe", "mutating"]
Verdict = Literal["allow", "deny", "needs_approval"]
ApprovalKind = Literal["scope", "mutating", "sensitive_fill", "sensitive_export"]


# #############################################################################
# ApprovalPolicy
# #############################################################################


class ApprovalPolicy(pydantic.BaseModel):
    """
    Which approval gates a policy turns on.

    :ivar mutating: Ask before a mutating control is activated.
    :ivar sensitive_fill:``literals`` asks for sensitive values the
        model or caller supplied while a value resolved from a policy-
        held secret reference runs unattended (the gate is keyed on
        risk, and the system entering its own login into an allowlisted
        app is the operator's everyday step); ``always`` gates secret
        references too; ``off`` never asks.
    :ivar sensitive_export: Ask before a sensitive value extracted in
        one app is typed into another.
    :ivar sensitive_field_patterns: Vendor-specific field names beyond
        the built-in detectors; ``financial:amount`` pins the class, a
        bare pattern counts as pii.
    """

    mutating: bool = True
    sensitive_fill: Literal["literals", "always", "off"] = "literals"
    sensitive_export: bool = True
    sensitive_field_patterns: List[str] = []


# #############################################################################
# ScopeGrant
# #############################################################################


class ScopeGrant(pydantic.BaseModel):
    """
    A human-approved widening of the static allowlists.

    Always coarse (a whole app, a whole registrable domain), never a
    one-off URL, so one approval covers the rest of the run and the
    generated profile.

    :ivar kind: Whether the grant names an app or a URL pattern.
    :ivar pattern: Exact app name, or a URL regex for the granted
        domain.
    :ivar reason: Why the grant was made.
    :ivar granted_by: Who made the grant.
    :ivar run_id: Run during which the grant was made.
    :ivar granted_at: ISO timestamp of the grant.
    """

    kind: Literal["app", "url"]
    pattern: str
    reason: str = ""
    granted_by: Literal["human", "config"] = "human"
    run_id: str = ""
    granted_at: str = ""


# #############################################################################
# ScopeRequest
# #############################################################################


@dataclasses.dataclass(frozen=True)
class ScopeRequest:
    """
    What the agent tried, and the coarse grant approving it would add.

    :ivar kind: Whether the request is for an app or a URL.
    :ivar value: The exact app name or URL that was attempted.
    :ivar proposed: The coarse pattern a grant would carry.
    :ivar reason: Why the agent tried it.
    """

    kind: Literal["app", "url"]
    value: str
    proposed: str
    reason: str


# #############################################################################
# ApprovalRequest
# #############################################################################


@dataclasses.dataclass(frozen=True)
class ApprovalRequest:
    """
    The question put to a human; everything in it is safe to log.

    :ivar kind: Which gate raised the question.
    :ivar summary: One-line description of what is being asked.
    :ivar details: Structured, printable context for the prompt.
    :ivar fingerprint: Identity of the question for remember-for-
        process.
    :ivar action_kind: Kind of the action that raised it.
    :ivar app: Application the action targets.
    :ivar step: Edge id at replay, when known.
    :ivar proposed_grants: Grants that would lift a scope block
        (``scope`` only).
    """

    kind: ApprovalKind
    summary: str
    details: Dict[str, str] = dataclasses.field(default_factory=dict)
    fingerprint: str = ""
    action_kind: str = ""
    app: str = ""
    step: str = ""
    proposed_grants: Tuple[ScopeGrant, ...] = ()


# #############################################################################
# ApprovalDecision
# #############################################################################


@dataclasses.dataclass(frozen=True)
class ApprovalDecision:
    """
    A recorded answer to an approval request.

    :ivar approved: Whether the action may proceed.
    :ivar remember: Whether the answer applies once or for the process.
    :ivar by: Which channel produced the answer.
    :ivar note: Free-text remark from the approver.
    """

    approved: bool
    remember: Literal["once", "process"] = "once"
    by: Literal[
        "tty", "console", "scripted", "cache", "timeout", "denied-by-default"
    ] = "scripted"
    note: str = ""


# #############################################################################
# PolicyDecision
# #############################################################################


@dataclasses.dataclass(frozen=True)
class PolicyDecision:
    """
    The outcome of evaluating one action against a policy.

    :ivar verdict:``allow``, ``deny``, or ``needs_approval``.
    :ivar risk: Whether the action mutates application state.
    :ivar reason: Human-readable explanation of the verdict.
    :ivar approval: The question to ask when ``needs_approval``.
    """

    verdict: Verdict
    risk: Risk
    reason: str
    approval: Optional[ApprovalRequest] = None

    @property
    def allowed(self) -> bool:
        """
        Whether the verdict is ``allow``.
        """
        is_allowed = self.verdict == "allow"
        return is_allowed


def fingerprint(
    kind: str, action: actions.SurfaceAction, *, app: str = ""
) -> str:
    """
    Compute the identity of an approval question.

    Covers everything that shapes the question and never the value being
    typed, so remember-for-process keys on the question alone.

    :param kind: The approval kind.
    :param action: The action that raised the question.
    :param app: Application the action targets.
    :return: A 16-character hex digest.
    """
    raw = "|".join(
        [
            kind,
            app,
            action.step,
            action.kind,
            action.target_text,
            action.data_class,
            action.export_from or "",
            action.app or "",
            action.url or "",
            action.key or "",
        ]
    )
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return digest
