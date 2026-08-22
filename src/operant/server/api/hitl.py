"""
Human-in-the-loop routes: approvals, interventions, clarifications.

Import as:

import operant.server.api.hitl as hitl
"""

from __future__ import annotations

import dataclasses
from typing import Annotated, Any

import fastapi

import operant.server.deps as deps
import operant.server.schemas as schemas

router = fastapi.APIRouter(tags=["hitl"])

State = Annotated[deps.ServerState, fastapi.Depends(deps.get_state)]


@router.get("/approvals")
def list_pending_approvals(state: State) -> Any:
    """
    List every approval awaiting an operator answer, oldest first.
    """
    items = [
        dataclasses.asdict(record) for record in state.runs.pending_approvals()
    ]
    return items


@router.get("/approvals/{approval_id}")
def get_approval(approval_id: str, state: State) -> Any:
    """
    Return one approval by id.
    """
    record = state.runs.get_approval(approval_id)
    if record is None:
        raise fastapi.HTTPException(status_code=404, detail="no such approval")
    data = dataclasses.asdict(record)
    return data


@router.post("/approvals/{approval_id}")
def answer_approval(
    approval_id: str, body: schemas.ApprovalDecisionBody, state: State
) -> Any:
    """
    Deliver the operator's decision to the waiting run.
    """
    state.manager.answer_approval(
        approval_id,
        approved=body.approved,
        remember=body.remember,
        note=body.note,
    )
    result = {"ok": True}
    return result


@router.post("/interventions/{intervention_id}/take")
def take_intervention(intervention_id: str, state: State) -> Any:
    """
    Transfer the live session to the operator.
    """
    state.manager.take_intervention(intervention_id)
    result = {"ok": True}
    return result


@router.post("/interventions/{intervention_id}/handback")
def hand_back(intervention_id: str, body: schemas.NoteBody, state: State) -> Any:
    """
    Return the live session to the automation.
    """
    state.manager.hand_back(intervention_id, body.note)
    result = {"ok": True}
    return result


@router.post("/interventions/{intervention_id}/abandon")
def abandon(intervention_id: str, body: schemas.NoteBody, state: State) -> Any:
    """
    End the run: the operator could not recover it.
    """
    state.manager.abandon(intervention_id, body.note)
    result = {"ok": True}
    return result


@router.post("/clarifications/{clarification_id}")
def answer_clarification(
    clarification_id: str, body: schemas.ClarificationAnswerBody, state: State
) -> Any:
    """
    Deliver the operator's clarifying answer to the waiting run.
    """
    state.manager.answer_clarification(clarification_id, body.answer)
    result = {"ok": True}
    return result


@router.post("/credentials/{request_id}")
def answer_credential(
    request_id: str, body: schemas.CredentialAnswerBody, state: State
) -> Any:
    """
    Deliver an operator-provided credential to the waiting run.

    The value or locator is passed to the worker in memory and never
    persisted.
    """
    state.manager.answer_credential(
        request_id, value=body.value, locator=body.locator
    )
    result = {"ok": True}
    return result
