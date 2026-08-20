"""
Human-in-the-loop ports: approvals and clarifying questions.

Import as:

import operant.ports.hitl as hitl
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    import operant.domain.approval as approval
    import operant.domain.secrets as secrets


# #############################################################################
# Approver
# #############################################################################


@runtime_checkable
class Approver(Protocol):
    """
    Answer approval requests the policy raises.
    """

    def ask(self, request: approval.ApprovalRequest) -> approval.ApprovalDecision:
        """
        Block until a decision arrives or the channel times out.

        :param request: What the human is being asked.
        :return: The decision, including who answered and whether to
            remember it.
        """
        ...


# #############################################################################
# Clarifier
# #############################################################################


@runtime_checkable
class Clarifier(Protocol):
    """
    Relays the discovery agent's questions to an operator.
    """

    def ask(self, question: str, *, run_id: str) -> str:
        """
        Block until the operator answers or dismisses.

        :param question: The agent's question.
        :param run_id: Run the question belongs to.
        :return: The answer, or ``""`` when there is none.
        """
        ...


# #############################################################################
# CredentialRequester
# #############################################################################


@runtime_checkable
class CredentialRequester(Protocol):
    """
    Ask a human for a credential the agent needs, out of the model's sight.
    """

    def request(
        self, name: str, *, run_id: str, reason: str
    ) -> Optional[secrets.CredentialGrant]:
        """
        Block until the human provides a credential or declines.

        The human either types a value or names an env/Keychain source;
        the returned grant never reaches the model, only the runtime.

        :param name: The reference name the model will use.
        :param run_id: Run the request belongs to.
        :param reason: Why the agent needs it (for the human).
        :return: The grant, or ``None`` when the human declines.
        """
        ...
