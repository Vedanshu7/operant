"""
Request and response bodies for the operator API.

Response shapes are built from the domain records the repositories
return, so the wire contract stays aligned with what runs actually
store. Request bodies are validated here before they reach the run
manager or repositories.

Import as:

import operant.server.schemas as schemas
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, Optional, Union

import pydantic

import operant.application.usecases.discover as discover
import operant.application.usecases.replay as replay
import operant.domain.models.runs as runs

# #############################################################################
# StartDiscoveryBody
# #############################################################################


class StartDiscoveryBody(pydantic.BaseModel):
    """
    A request to start an LLM discovery run.

    :ivar goal: Natural-language goal to discover.
    :ivar capability_id: Id to save the resulting capability under.
    :ivar name: Human-readable capability name; defaults to the id.
    :ivar profile_id: Profile to run under; ``None`` bootstraps a
        vendor.
    :ivar tenant: Tenant to run against.
    :ivar inputs: Pre-seeded task inputs.
    :ivar screenshots: Whether to send the model screenshots.
    :ivar max_turns: Override the turn budget; ``None`` uses the
        default.
    """

    goal: str
    capability_id: str
    name: str = ""
    profile_id: Optional[str] = None
    tenant: str = ""
    inputs: Dict[str, str] = pydantic.Field(default_factory=dict)
    screenshots: bool = True
    max_turns: Optional[int] = None

    def to_request(self) -> discover.DiscoverRequest:
        """
        Build the use-case request.
        """
        request = discover.DiscoverRequest(
            goal=self.goal,
            capability_id=self.capability_id,
            name=self.name,
            profile_id=self.profile_id,
            tenant=self.tenant,
            inputs=dict(self.inputs),
            screenshots=self.screenshots,
            max_turns=self.max_turns,
        )
        return request


# #############################################################################
# StartReplayBody
# #############################################################################


class StartReplayBody(pydantic.BaseModel):
    """
    A request to replay a capability.

    :ivar capability_id: Capability to replay.
    :ivar tenant: Tenant override; the capability default when empty.
    :ivar inputs: Task inputs by name.
    :ivar inject_session_expiry_before: Edge id to fault before, for
        demos.
    """

    capability_id: str
    tenant: str = ""
    inputs: Dict[str, str] = pydantic.Field(default_factory=dict)
    inject_session_expiry_before: Optional[str] = None

    def to_request(self) -> replay.ReplayRequest:
        """
        Build the use-case request.
        """
        request = replay.ReplayRequest(
            capability_id=self.capability_id,
            tenant=self.tenant,
            inputs=dict(self.inputs),
            inject_session_expiry_before=self.inject_session_expiry_before,
        )
        return request


# #############################################################################
# ApprovalDecisionBody
# #############################################################################


class ApprovalDecisionBody(pydantic.BaseModel):
    """
    An operator's answer to an approval question.

    :ivar approved: Whether the action is allowed.
    :ivar remember:``once`` or ``process`` (remember for the run).
    :ivar note: Optional operator remark.
    """

    approved: bool
    remember: str = "once"
    note: str = ""


# #############################################################################
# ClarificationAnswerBody
# #############################################################################


class ClarificationAnswerBody(pydantic.BaseModel):
    """
    An operator's answer to a clarifying question.

    :ivar answer: The free-text answer.
    """

    answer: str


# #############################################################################
# CredentialAnswerBody
# #############################################################################


class CredentialAnswerBody(pydantic.BaseModel):
    """
    An operator's answer to a credential request (never persisted).

    Exactly one is set: ``value`` is a literal the operator typed,
    ``locator`` names an ``env:`` / ``keychain:`` source to resolve.

    :ivar value: A typed credential value.
    :ivar locator: A source locator to resolve instead of a value.
    """

    value: Optional[str] = None
    locator: Optional[str] = None


# #############################################################################
# NoteBody
# #############################################################################


class NoteBody(pydantic.BaseModel):
    """
    A note attached to an intervention action.

    :ivar note: Optional operator remark.
    """

    note: str = ""


# #############################################################################
# SecretRefBody
# #############################################################################


class SecretRefBody(pydantic.BaseModel):
    """
    A secret reference's metadata (never a value).

    :ivar name: Reference name used as ``$secret:<name>``.
    :ivar backend:``env`` or ``keychain``.
    :ivar locator: Backend locator (env var, or ``service/account``).
    :ivar description: What the secret is for.
    """

    name: str
    backend: str
    locator: str
    description: str = ""

    def to_meta(self) -> runs.SecretRefMeta:
        """
        Build the repository metadata record.
        """
        meta = runs.SecretRefMeta(
            name=self.name,
            backend=self.backend,  # type: ignore[arg-type]
            locator=self.locator,
            description=self.description,
        )
        return meta


def run_summary(run: runs.RunRecord) -> Dict[str, Any]:
    """
    Render a run as the summary shape the frontend expects.
    """
    summary = {
        "id": run.id,
        "kind": run.kind,
        "status": run.status,
        "goal": run.goal or None,
        "capability_id": run.capability_id,
        "vendor_id": run.vendor_id or None,
        "profile_id": run.vendor_id or None,
        "tenant": run.tenant or None,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }
    return summary


def run_detail(
    run: runs.RunRecord,
    *,
    pending_approval: Optional[runs.ApprovalRecord],
    pending_intervention: Optional[runs.InterventionRecord],
    pending_clarification: Optional[runs.ClarificationRecord],
    lease_position: Optional[int],
) -> Dict[str, Any]:
    """
    Render a run plus its pending human-in-the-loop state.
    """
    detail = run_summary(run)
    detail.update(
        {
            "inputs": run.inputs,
            "result": run.result.model_dump() if run.result else None,
            "error": run.error,
            "evidence_dir": run.evidence_dir or None,
            "pending_approval": _asdict(pending_approval),
            "pending_intervention": _asdict(pending_intervention),
            "pending_clarification": _asdict(pending_clarification),
            "lease_position": lease_position,
        }
    )
    return detail


def _asdict(
    record: Optional[
        Union[
            runs.ApprovalRecord, runs.InterventionRecord, runs.ClarificationRecord
        ]
    ],
) -> Optional[Dict[str, Any]]:
    """
    Serialise a pending HITL record to a dict, or ``None`` when absent.
    """
    if record is None:
        result = None
    else:
        result = dataclasses.asdict(record)
    return result
