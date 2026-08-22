"""
Typed evidence events: registry round-trips and closed schemas.
"""

from __future__ import annotations

import json
from typing import Any, Literal, get_args, get_origin

import pydantic
import pytest

import operant.domain.events as events


def _sample(annotation: Any) -> Any:
    if get_origin(annotation) is Literal:
        return get_args(annotation)[0]
    origin = get_origin(annotation)
    if origin in (list, tuple, set, frozenset):
        return []
    if origin is dict:
        return {}
    text = str(annotation)
    if "bool" in text:
        return True
    if "int" in text:
        return 1
    return "x"


def test_every_registered_event_round_trips() -> None:
    for type_name, model in events.EVENT_REGISTRY.items():
        required = {
            name: _sample(field.annotation)
            for name, field in model.model_fields.items()
            if field.is_required() and name != "type"
        }
        event = model.model_validate({"type": type_name, **required})
        again = events.event_adapter.validate_python(
            json.loads(event.model_dump_json(by_alias=True))
        )
        assert again.type == type_name
        assert type(again) is model


def test_registry_keys_match_type_defaults() -> None:
    for type_name, model in events.EVENT_REGISTRY.items():
        assert model.model_fields["type"].default == type_name


def test_new_lifecycle_events_are_registered() -> None:
    assert events.EVENT_REGISTRY["run_status"] is events.RunStatusChanged
    assert (
        events.EVENT_REGISTRY["clarification_answered"]
        is events.ClarificationAnswered
    )
    status = events.event_adapter.validate_python(
        {"type": "run_status", "status": "running"}
    )
    assert isinstance(status, events.RunStatusChanged)
    answered = events.event_adapter.validate_python(
        {"type": "clarification_answered", "question": "q?", "answered": True}
    )
    assert isinstance(answered, events.ClarificationAnswered)


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(pydantic.ValidationError):
        events.InputDeclared(  # type: ignore[call-arg]
            name="a", value="b", surprise="nope"
        )


def test_approval_resolved_by_is_closed() -> None:
    with pytest.raises(pydantic.ValidationError):
        events.ApprovalResolved(kind="mutating", approved=True, by="bogus")


def test_unknown_event_type_is_rejected() -> None:
    with pytest.raises(pydantic.ValidationError):
        events.event_adapter.validate_python(
            {"type": "input_delcared", "name": "x", "value": "1"}
        )


def test_control_transition_uses_from_to_aliases() -> None:
    event = events.ControlTransition.model_validate(
        {"type": "control_transition", "from": "system", "to": "human"}
    )
    assert event.from_state == "system"
    dumped = json.loads(event.model_dump_json(by_alias=True))
    assert dumped["from"] == "system"
    assert dumped["to"] == "human"
