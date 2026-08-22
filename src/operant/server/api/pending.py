"""
Helpers to find a run's currently pending human-in-the-loop rows.

Import as:

import operant.server.api.pending as pending
"""

from __future__ import annotations

from typing import Optional

import operant.domain.models.runs as mrruns
import operant.infra.repositories.runs as rrruns

_OPEN_INTERVENTION = frozenset({"paused", "human"})


def pending_approval(
    runs: rrruns.SqlRunRepository, run_id: str
) -> Optional[mrruns.ApprovalRecord]:
    """
    Return the run's pending approval, if one awaits an answer.
    """
    found = None
    for record in runs.run_approvals(run_id):
        if record.status == "pending":
            found = record
            break
    return found


def pending_intervention(
    runs: rrruns.SqlRunRepository, run_id: str
) -> Optional[mrruns.InterventionRecord]:
    """
    Return the run's open intervention, if a human is needed.
    """
    found = None
    for record in runs.run_interventions(run_id):
        if record.state in _OPEN_INTERVENTION:
            found = record
            break
    return found


def pending_clarification(
    runs: rrruns.SqlRunRepository, run_id: str
) -> Optional[mrruns.ClarificationRecord]:
    """
    Return the run's pending clarifying question, if one awaits.
    """
    found = None
    for record in runs.run_clarifications(run_id):
        if record.status == "pending":
            found = record
            break
    return found
