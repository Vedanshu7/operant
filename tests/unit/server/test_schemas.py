"""
Request-schema tests for starting runs over the API.
"""

from __future__ import annotations

import pydantic
import pytest

import operant.server.schemas as schemas


def test_discovery_requests_carry_the_agent_mode() -> None:
    body = schemas.StartDiscoveryBody(goal="g", capability_id="c", agents="multi")
    assert body.to_request().agents == "multi"
    assert (
        schemas.StartDiscoveryBody(goal="g", capability_id="c")
        .to_request()
        .agents
        is None
    )


def test_an_unknown_agent_mode_is_rejected() -> None:
    with pytest.raises(pydantic.ValidationError):
        schemas.StartDiscoveryBody(goal="g", capability_id="c", agents="swarm")
