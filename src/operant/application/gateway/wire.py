"""
JSON wire format for the driver protocol.

The wire is OS-neutral: a Windows or Linux driver daemon speaks exactly
the same shapes; only the tools behind it differ. Encoders use
``dataclasses.asdict`` / ``model_dump``; decoders reconstruct by
filtering to known fields, so adding a field to a model cannot silently
drift the codec.

The protocol version is bumped when these shapes change; the client
refuses a daemon that speaks another version instead of failing
obscurely mid-run.

Import as:

import operant.application.gateway.wire as wire
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, Final

import operant.domain.approval as approval
import operant.domain.models.actions as actions
import operant.domain.models.digest as digest

PROTOCOL_VERSION: Final = "2"


def _rebuild[T](cls: type[T], data: Dict[str, Any]) -> T:
    """
    Build a dataclass from ``data``, ignoring unknown keys.
    """
    known = {f.name for f in dataclasses.fields(cls)}  # type: ignore[arg-type]
    obj = cls(**{k: v for k, v in data.items() if k in known})
    return obj


def digest_to_dict(screen: digest.ScreenDigest) -> Dict[str, Any]:
    """
    Serialise a screen digest.
    """
    data = dataclasses.asdict(screen)
    return data


def digest_from_dict(data: Dict[str, Any]) -> digest.ScreenDigest:
    """
    Reconstructs a screen digest, including its controls and boxes.
    """
    controls = tuple(
        _rebuild(
            digest.Control,
            {
                **control,
                "box": digest.Box(**control["box"]),
                "actions": tuple(control.get("actions", ())),
            },
        )
        for control in data.get("controls", [])
    )
    screen = _rebuild(digest.ScreenDigest, {**data, "controls": controls})
    return screen


def action_to_dict(action: actions.SurfaceAction) -> Dict[str, Any]:
    """
    Serialise a surface action.
    """
    data = dataclasses.asdict(action)
    return data


def action_from_dict(data: Dict[str, Any]) -> actions.SurfaceAction:
    """
    Reconstructs a surface action, keeping every sensitivity tag.
    """
    action = _rebuild(actions.SurfaceAction, data)
    return action


def approval_request_to_dict(
    request: approval.ApprovalRequest,
) -> Dict[str, Any]:
    """
    Serialise an approval request, expanding its proposed grants.
    """
    payload = dataclasses.asdict(request)
    payload["proposed_grants"] = [
        grant.model_dump(mode="json") for grant in request.proposed_grants
    ]
    return payload


def approval_request_from_dict(
    data: Dict[str, Any],
) -> approval.ApprovalRequest:
    """
    Reconstructs an approval request and its proposed grants.
    """
    grants = tuple(
        approval.ScopeGrant.model_validate(grant)
        for grant in data.get("proposed_grants", [])
    )
    request = _rebuild(
        approval.ApprovalRequest, {**data, "proposed_grants": grants}
    )
    return request


def decision_to_dict(
    decision: approval.PolicyDecision,
) -> Dict[str, Any]:
    """
    Serialise a policy decision for the daemon's 403 payloads.
    """
    payload = {
        "verdict": decision.verdict,
        "allowed": decision.allowed,
        "risk": decision.risk,
        "reason": decision.reason,
        "approval_kind": (decision.approval.kind if decision.approval else None),
    }
    return payload
