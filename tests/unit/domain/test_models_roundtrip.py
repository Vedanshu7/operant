"""
Persisted graphs and artifacts load, dump, and reload unchanged.
"""

from __future__ import annotations

import json
import pathlib
from typing import Dict

import pytest

import operant.domain.models.artifact as artifact
import operant.domain.models.graph as graph

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
GRAPH_FILES = sorted((REPO_ROOT / "graphs").glob("**/v*.json"))
ARTIFACT_FILES = sorted((REPO_ROOT / "artifacts").glob("*.json"))


def _load(path: pathlib.Path) -> Dict[str, object]:
    with path.open(encoding="utf-8") as f:
        data: Dict[str, object] = json.load(f)
    return data


def test_schema_version_is_pinned() -> None:
    assert artifact.SCHEMA_VERSION == "2.3"
    assert graph.SCHEMA_VERSION == artifact.SCHEMA_VERSION


def test_fixture_sets_are_not_empty() -> None:
    assert GRAPH_FILES
    assert ARTIFACT_FILES


@pytest.mark.parametrize(
    "path", GRAPH_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_app_graph_round_trips(path: pathlib.Path) -> None:
    loaded = graph.AppGraph.model_validate(_load(path))
    again = graph.AppGraph.model_validate(loaded.model_dump(by_alias=True))
    assert again == loaded
    assert again.model_dump(by_alias=True) == loaded.model_dump(by_alias=True)


@pytest.mark.parametrize(
    "path", ARTIFACT_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_capability_artifact_round_trips(path: pathlib.Path) -> None:
    loaded = artifact.CapabilityArtifact.model_validate(_load(path))
    again = artifact.CapabilityArtifact.model_validate(
        loaded.model_dump(by_alias=True)
    )
    assert again == loaded
    assert again.model_dump(by_alias=True) == loaded.model_dump(by_alias=True)


def test_edge_serialises_from_and_to_by_alias() -> None:
    edge = graph.Edge(
        id="e1",
        from_node="a",
        to_node="b",
        description="go",
        action=graph.Action(kind="click"),
    )
    dumped = edge.model_dump(by_alias=True)
    assert dumped["from"] == "a"
    assert dumped["to"] == "b"
    assert graph.Edge.model_validate(dumped) == edge


def test_tenant_binding_entry_path_defaults_empty() -> None:
    binding = artifact.TenantBinding(base_url="http://localhost:8080")
    assert binding.entry_path == ""
    assert binding.secret_refs == {}
