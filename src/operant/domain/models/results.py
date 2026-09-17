"""
The replay result contract and failure taxonomy.

Every replay ends in exactly one of four results, discriminated by
``status``: success, a business outcome the application reported, an
escalation to a human, or a classified failure. ``FailureClass`` is the
closed vocabulary shared with graph ``FailHandle`` detectors.

Import as:

import operant.domain.models.results as results
"""

from __future__ import annotations

from typing import Annotated, Dict, Final, List, Literal, Union

import pydantic

FailureClass = Literal[
    "locator_not_found",
    "locator_ambiguous",
    "node_assert_failed",
    "extraction_missing",
    "unreviewed_step",
    "precondition_failed",
    "timeout",
    "session_expired",
    "unexpected_dialog",
    "app_error",
    "launch_failed",
    "policy_violation",
    "approval_denied",
    "cancelled",
]


# #############################################################################
# SuccessResult
# #############################################################################


class SuccessResult(pydantic.BaseModel):
    """
    The capability reached its goal and extracted its outputs.

    :ivar status: discriminator, always ``success``.
    :ivar outputs: extracted output values keyed by output name.
    :ivar evidence_dir: directory holding the run's evidence.
    """

    status: Literal["success"] = "success"
    outputs: Dict[str, str]
    evidence_dir: str
    drifted: List[str] = []


# #############################################################################
# BusinessOutcomeResult
# #############################################################################


class BusinessOutcomeResult(pydantic.BaseModel):
    """
    The application reported a business outcome instead of the goal.

    :ivar status: discriminator, always ``business_outcome``.
    :ivar outcome: outcome name from the matching detector.
    :ivar detail: human-readable detail from the detector.
    :ivar evidence_dir: directory holding the run's evidence.
    """

    status: Literal["business_outcome"] = "business_outcome"
    outcome: str
    detail: str
    evidence_dir: str


# #############################################################################
# EscalatedResult
# #############################################################################


class EscalatedResult(pydantic.BaseModel):
    """
    Control was handed to a human during the run.

    :ivar status: discriminator, always ``escalated``.
    :ivar intervention_id: id of the intervention that took over.
    :ivar resolution: how the human resolved it.
    :ivar evidence_dir: directory holding the run's evidence.
    """

    status: Literal["escalated"] = "escalated"
    intervention_id: str
    resolution: Literal[
        "completed_by_human", "resumed_and_completed", "abandoned"
    ]
    evidence_dir: str


# #############################################################################
# Failure
# #############################################################################


class Failure(pydantic.BaseModel):
    """
    A classified failure at one edge.

    :ivar at_edge: id of the edge that failed.
    :ivar failure_class: closed failure vocabulary entry.
    :ivar expected: what replay expected to see.
    :ivar observed: what replay observed instead.
    :ivar evidence_refs: evidence files that document the failure.
    """

    at_edge: str
    failure_class: FailureClass
    expected: str
    observed: str
    evidence_refs: List[str] = []


# #############################################################################
# FailureResult
# #############################################################################


class FailureResult(pydantic.BaseModel):
    """
    The run stopped on a classified failure.

    :ivar status: discriminator, always ``failure``.
    :ivar failure: the classified failure.
    :ivar evidence_dir: directory holding the run's evidence.
    """

    status: Literal["failure"] = "failure"
    failure: Failure
    evidence_dir: str


ReplayResult = Annotated[
    Union[SuccessResult, BusinessOutcomeResult, EscalatedResult, FailureResult],
    pydantic.Field(discriminator="status"),
]

result_adapter: Final[pydantic.TypeAdapter[ReplayResult]] = pydantic.TypeAdapter(
    ReplayResult
)
"""
Validate a serialised ``ReplayResult`` back into its concrete type.
"""
