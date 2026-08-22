"""
Builders for capability artifacts and graph pieces used by replay tests.
"""

from __future__ import annotations

from typing import Any, Dict

import operant.domain.models.artifact as artifact
import operant.domain.models.graph as graph


def node(node_id: str, pattern: str) -> graph.Node:
    """
    Build a node asserting a window-title pattern.
    """
    return graph.Node(
        id=node_id,
        description=node_id,
        checks=[graph.TitleMatches(pattern=pattern)],
    )


def edge(payload: Dict[str, Any]) -> graph.Edge:
    """
    Validate an edge from its JSON shape (aliases included).
    """
    return graph.Edge.model_validate(payload)


def capability(**over: Any) -> artifact.CapabilityArtifact:
    """
    Build a minimal capability; override any field via kwargs.
    """
    base: Dict[str, Any] = {
        "id": "c",
        "name": "c",
        "description": "c",
        "vendor_id": "app",
        "graph_version": 1,
        "tenants": {"t": artifact.TenantBinding(base_url="http://x")},
        "default_tenant": "t",
        "start_node": "home",
        "goal_node": "goal",
        "compiled_path": [],
        "policy_scope": artifact.PolicyScope(
            policy_id="p",
            required_action_kinds=[],
            touches_mutating_edges=False,
        ),
        "provenance": artifact.Provenance(
            discovery_run_id="r", model="m", recorded_at="t", goal="g"
        ),
    }
    base.update(over)
    return artifact.CapabilityArtifact(**base)
