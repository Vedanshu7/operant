"""
The multi-agent discovery plan: subgoals, and the verifier's verdicts.

Pure data, validated because the planner model writes it.

Import as:

import operant.domain.models.plan as mdplan
"""

from __future__ import annotations

import re
from typing import Final, List

import pydantic

# A credential is referenced by a short name, never by its value.
_NAME_RE: Final = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,39}$")


# #############################################################################
# Subgoal
# #############################################################################


class Subgoal(pydantic.BaseModel):
    """
    One checkable step of the goal.

    :ivar id: Short stable id, e.g. ``s1``.
    :ivar description: What the executor should achieve.
    :ivar success_criteria: What the screen shows when it is achieved.
    :ivar expected_outputs: Output names this subgoal must extract.
    """

    id: str
    description: str
    success_criteria: str
    expected_outputs: List[str] = []


# #############################################################################
# Plan
# #############################################################################


class Plan(pydantic.BaseModel):
    """
    The planner's decomposition of the goal.

    :ivar subgoals: Ordered subgoals; at least one.
    :ivar required_inputs: Names of task inputs the goal implies.
    :ivar credential_names: Names of credentials needed; never values.
    """

    subgoals: List[Subgoal] = pydantic.Field(min_length=1)
    required_inputs: List[str] = []
    credential_names: List[str] = []

    @pydantic.field_validator("credential_names")
    @classmethod
    def _names_only(cls, names: List[str]) -> List[str]:
        """
        Reject anything that is not a short credential name.
        """
        bad = [name for name in names if not _NAME_RE.match(name)]
        if bad:
            raise ValueError(
                "credential_names must be short names like 'password', "
                f"never values: {len(bad)} entries rejected"
            )
        return names

    @pydantic.model_validator(mode="after")
    def _unique_ids(self) -> Plan:
        """
        Require distinct subgoal ids.
        """
        ids = [subgoal.id for subgoal in self.subgoals]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate subgoal ids in {ids}")
        return self


def single_step(goal: str) -> Plan:
    """
    Build the fallback plan: the whole goal as one subgoal.

    :param goal: The natural-language goal.
    :return: A one-subgoal plan.
    """
    plan = Plan(
        subgoals=[
            Subgoal(
                id="s1",
                description=goal,
                success_criteria="the goal is fully achieved on screen",
            )
        ]
    )
    return plan


# #############################################################################
# Verdict
# #############################################################################


class Verdict(pydantic.BaseModel):
    """
    A verifier's decision on one subgoal.

    :ivar passed: Whether the subgoal is achieved.
    :ivar reason: Why, in one or two sentences.
    :ivar reviewer: Which panel member decided.
    """

    passed: bool
    reason: str
    reviewer: str = "verifier"
