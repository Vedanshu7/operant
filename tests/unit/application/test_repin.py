"""
Moving a capability to another graph version.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

import operant.application.capabilities as apcapab
import operant.domain.errors as errors
import operant.domain.models.graph as graph
import tests.support.capabilities as capab


def _node(node_id: str) -> graph.Node:
    return capab.node(node_id, node_id)


def _edge(edge_id: str, start: str, end: str, **fields: Any) -> graph.Edge:
    return capab.edge(
        {
            "id": edge_id,
            "from": start,
            "to": end,
            "description": edge_id,
            "action": {"kind": "click"},
            **fields,
        }
    )


# #############################################################################
# _Graphs
# #############################################################################


class _Graphs:

    def __init__(self, *versions: graph.AppGraph) -> None:
        self.stored = {g.graph_version: g for g in versions}

    def get(self, vendor: str, version: Optional[int] = None) -> graph.AppGraph:
        return self.stored[version or max(self.stored)]

    def exists(self, vendor: str) -> bool:
        return vendor == "callee"


# #############################################################################
# _Artifacts
# #############################################################################


class _Artifacts:

    def __init__(self) -> None:
        self.saved: List[Any] = []

    def save_new_version(self, document: Any) -> Any:
        self.saved.append(document)
        return document


# #############################################################################
# _Runs
# #############################################################################


class _Runs:

    def __init__(self) -> None:
        self.closed: List[str] = []
        self.audited: List[Any] = []

    def close_samples(self, capability_id: str) -> None:
        self.closed.append(capability_id)

    def audit(self, entry: Any) -> None:
        self.audited.append(entry)


CAPABILITY = capab.capability(
    start_node="a",
    goal_node="b",
    compiled_path=["e1"],
    graph_version=1,
).model_copy(update={"status": "approved"})
OLD = graph.AppGraph(
    vendor_id=CAPABILITY.vendor_id,
    graph_version=1,
    nodes=[_node("a"), _node("b")],
    edges=[_edge("e1", "a", "b")],
)


def _repin(new: graph.AppGraph, **kwargs: Dict[str, Any]) -> Any:
    artifacts, runs = _Artifacts(), _Runs()
    moved = apcapab.repin(
        CAPABILITY,
        graph_store=_Graphs(OLD, new),
        artifact_store=artifacts,
        run_repo=runs,
        by="test",
        **kwargs,
    )
    return moved, artifacts, runs


def test_a_capability_moves_as_a_draft_and_starts_a_new_record() -> None:
    new = OLD.model_copy(update={"graph_version": 2})
    moved, artifacts, runs = _repin(new)
    assert (moved.graph_version, moved.status) == (2, "draft")
    assert len(artifacts.saved) == 1
    assert runs.closed == [CAPABILITY.id]
    assert runs.audited[0].action == "repin_artifact"


def test_the_same_version_changes_nothing() -> None:
    moved, artifacts, _ = _repin(OLD, version=1)
    assert moved.status == "approved"
    assert artifacts.saved == []


@pytest.mark.parametrize(
    "edges, nodes, expected",
    [
        ([], ["a", "b"], "edge e1 is gone"),
        ([_edge("e1", "a", "b", retired_in=2)], ["a", "b"], "edge e1 is retired"),
        ([_edge("e1", "a", "b")], ["a"], "goal node b is gone"),
    ],
)
def test_a_broken_path_is_refused_with_the_reason(edges, nodes, expected) -> None:
    new = OLD.model_copy(
        update={
            "graph_version": 2,
            "edges": edges,
            "nodes": [_node(n) for n in nodes],
        }
    )
    with pytest.raises(errors.RepinRefusedError, match=expected):
        _repin(new)


def test_a_start_of_anywhere_needs_no_node() -> None:
    anywhere = CAPABILITY.model_copy(update={"start_node": "*"})
    new = OLD.model_copy(update={"graph_version": 2})
    assert apcapab._repin_problems(anywhere, new, _Graphs(new)) == []


def test_a_path_that_no_longer_chains_is_refused() -> None:
    chained = CAPABILITY.model_copy(update={"compiled_path": ["e1", "e2"]})
    new = OLD.model_copy(
        update={
            "graph_version": 2,
            "nodes": [_node("a"), _node("b"), _node("c")],
            "edges": [_edge("e1", "a", "b"), _edge("e2", "c", "b")],
        }
    )
    problems = apcapab._repin_problems(chained, new, _Graphs(new))
    assert problems == ["edge e2 no longer follows e1"]


def test_an_invoke_needs_its_callee() -> None:
    invoke = capab.edge(
        {
            "id": "e1",
            "from": "a",
            "to": "b",
            "description": "call",
            "action": {
                "kind": "invoke",
                "graph_ref": {"graph_id": "gone", "target_node": "x"},
            },
        }
    )
    assert apcapab._invoke_problems(invoke, _Graphs(OLD)) == [
        "edge e1 invokes missing gone"
    ]
