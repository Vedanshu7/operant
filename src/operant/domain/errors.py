"""
Exception hierarchy shared by every layer.

All Operant exceptions derive from ``OperantError`` so callers can catch
the family they care about. Policy exceptions carry structured payloads
(the approval request, the decision) because the approval loop and the
HTTP layer both act on them.

Import as:

import operant.domain.errors as errors
"""

from __future__ import annotations

import collections.abc
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    import operant.domain.approval as approval
    import operant.domain.models.actions as actions
    import operant.domain.models.tools as tools


# #############################################################################
# OperantError
# #############################################################################


class OperantError(Exception):
    """
    Base class for all Operant errors.
    """


# #############################################################################
# ConfigError
# #############################################################################


class ConfigError(OperantError):
    """
    Settings or profile content is invalid or missing.
    """


# #############################################################################
# SurfaceError
# #############################################################################


class SurfaceError(OperantError):
    """
    The actuation surface could not observe or act.
    """


# #############################################################################
# DriverError
# #############################################################################


class DriverError(SurfaceError):
    """
    The driver daemon is unreachable or answered with an error.
    """


# #############################################################################
# NoToolAvailableError
# #############################################################################


class NoToolAvailableError(SurfaceError):
    """
    No healthy tool serves the requested action kind.

    :ivar kind: The action kind no tool could serve.
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


# #############################################################################
# AllToolsFailedError
# #############################################################################


class AllToolsFailedError(SurfaceError):
    """
    Every tool in the fallback chain failed for the action.

    :ivar kind: The action kind every tool failed to serve.
    :ivar attempts: One entry per tool tried, in chain order.
    """

    def __init__(
        self, kind: str, attempts: collections.abc.Sequence[tools.Attempt]
    ) -> None:
        detail = "; ".join(f"{a.tool}: {a.status} ({a.reason})" for a in attempts)
        super().__init__(f'every tool for "{kind}" failed - {detail}')
        self.kind = kind
        self.attempts = tuple(attempts)


# #############################################################################
# TargetNotFoundError
# #############################################################################


class TargetNotFoundError(SurfaceError):
    """
    No control on screen satisfied the target strategies.
    """


# #############################################################################
# PolicyError
# #############################################################################


class PolicyError(OperantError):
    """
    Base for policy decisions that stop an action.
    """


# #############################################################################
# PolicyViolationError
# #############################################################################


class PolicyViolationError(PolicyError):
    """
    The policy denied the action outright.

    :ivar decision: The policy decision that denied the action.
    """

    def __init__(self, decision: approval.PolicyDecision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


# #############################################################################
# ApprovalRequiredError
# #############################################################################


class ApprovalRequiredError(PolicyError):
    """
    The action needs a human decision before it can run.

    :ivar request: What the human is being asked.
    :ivar nonce: Single-use token that authorises the retry once
        approved.
    :ivar action: The action that triggered the request.
    """

    def __init__(
        self,
        request: approval.ApprovalRequest,
        nonce: str,
        action: actions.SurfaceAction,
    ) -> None:
        super().__init__(request.summary)
        self.request = request
        self.nonce = nonce
        self.action = action


# #############################################################################
# ApprovalDeniedError
# #############################################################################


class ApprovalDeniedError(PolicyError):
    """
    A human (or a timeout) said no.

    :ivar request: The question that was asked.
    :ivar decision: The recorded answer.
    """

    def __init__(
        self,
        request: approval.ApprovalRequest,
        decision: approval.ApprovalDecision,
    ) -> None:
        super().__init__(f"denied: {request.summary}")
        self.request = request
        self.decision = decision


# #############################################################################
# SecretError
# #############################################################################


class SecretError(OperantError):
    """
    Base for secret resolution problems.
    """


# #############################################################################
# SecretNotFoundError
# #############################################################################


class SecretNotFoundError(SecretError):
    """
    A referenced secret has no value in the configured store.

    :ivar name: The reference name the caller asked for.
    :ivar available: Reference names the tenant declares.
    """

    def __init__(self, name: str, available: List[str]) -> None:
        super().__init__(f'No secret "{name}". Available: {available}')
        self.name = name
        self.available = available


# #############################################################################
# SecretBackendUnavailableError
# #############################################################################


class SecretBackendUnavailableError(SecretError):
    """
    The secret store cannot be used on this host or configuration.
    """


# #############################################################################
# RepositoryError
# #############################################################################


class RepositoryError(OperantError):
    """
    Base for persistence problems.
    """


# #############################################################################
# NotFoundError
# #############################################################################


class NotFoundError(RepositoryError):
    """
    The requested record does not exist.
    """


# #############################################################################
# VersionConflictError
# #############################################################################


class VersionConflictError(RepositoryError):
    """
    A write raced another writer on the same versioned record.
    """


# #############################################################################
# SchemaVersionUnsupportedError
# #############################################################################


class SchemaVersionUnsupportedError(RepositoryError):
    """
    A stored document declares a schema this build cannot read.
    """


# #############################################################################
# ReplayError
# #############################################################################


class ReplayError(OperantError):
    """
    Base for replay-time failures that are not policy decisions.
    """


# #############################################################################
# PreconditionFailedError
# #############################################################################


class PreconditionFailedError(ReplayError):
    """
    Inputs, tenant, or start state did not satisfy the capability.
    """


# #############################################################################
# InvokeDepthExceededError
# #############################################################################


class InvokeDepthExceededError(ReplayError):
    """
    Cross-graph composition recursed deeper than allowed.
    """


# #############################################################################
# DiscoveryError
# #############################################################################


class DiscoveryError(OperantError):
    """
    Base for discovery-loop failures.
    """


# #############################################################################
# LlmError
# #############################################################################


class LlmError(DiscoveryError):
    """
    The model call failed.

    :ivar retryable: Whether a retry could reasonably succeed.
    """

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


# #############################################################################
# ToolArgumentError
# #############################################################################


class ToolArgumentError(DiscoveryError):
    """
    The model called a tool with arguments that cannot be acted on.
    """


# #############################################################################
# ClarificationUnavailableError
# #############################################################################


class ClarificationUnavailableError(DiscoveryError):
    """
    The model asked a question but no clarification channel exists.
    """


# #############################################################################
# ControlError
# #############################################################################


class ControlError(OperantError):
    """
    Base for control-transfer problems.
    """


# #############################################################################
# InvalidTransitionError
# #############################################################################


class InvalidTransitionError(ControlError):
    """
    The broker was asked to move between incompatible states.
    """


# #############################################################################
# UnknownInterventionError
# #############################################################################


class UnknownInterventionError(ControlError):
    """
    No pending intervention has the given id.
    """


# #############################################################################
# UnknownApprovalError
# #############################################################################


class UnknownApprovalError(ControlError):
    """
    No pending approval has the given id.
    """
