"""
Splitting a graph into two linked by an invoke edge.
"""

from __future__ import annotations

import pytest

import operant.domain.graph.split as split
import operant.domain.models.graph as mggraph


def node(nid: str) -> mggraph.Node:
    return mggraph.Node(
        id=nid,
        description=nid,
        checks=[mggraph.TitleMatches(pattern=nid)],
    )


def edge(eid: str, frm: str, to: str, kind: str = "click") -> mggraph.Edge:
    return mggraph.Edge.model_validate(
        {
            "id": eid,
            "from": frm,
            "to": to,
            "description": eid,
            "action": {"kind": kind},
        }
    )


def test_split_extracts_and_rewrites_to_invoke() -> None:
    # app: a -> b -> settings1 -> settings2; extract the settings domain.
    graph = mggraph.AppGraph(
        vendor_id="app",
        app_name="Chrome",
        window_title_pattern="App",
        nodes=[node("a"), node("b"), node("settings1"), node("settings2")],
        edges=[
            edge("e1", "a", "b"),
            edge("e2", "b", "settings1"),
            edge("e3", "settings1", "settings2"),
        ],
    )
    rewritten, new = split.split_graph(
        graph,
        {"settings1", "settings2"},
        "system-settings",
        new_app_name="System Settings",
        new_window_title_pattern="System Settings",
    )
    # New graph owns the extracted domain.
    assert {n.id for n in new.nodes} == {"settings1", "settings2"}
    assert [e.id for e in new.edges] == ["e3"]
    assert new.app_name == "System Settings"
    # Original no longer contains the extracted nodes...
    assert {n.id for n in rewritten.nodes} == {"a", "b"}
    # ...and the crossing edge (b -> settings1) became an invoke back to b.
    invoke_edges = [e for e in rewritten.edges if e.action.kind == "invoke"]
    assert len(invoke_edges) == 1
    inv = invoke_edges[0]
    assert inv.from_node == "b"
    assert inv.to_node == "b"
    assert inv.action.graph_ref is not None
    assert inv.action.graph_ref.graph_id == "system-settings"
    assert inv.action.graph_ref.target_node == "settings1"


def test_split_rejects_unknown_nodes() -> None:
    graph = mggraph.AppGraph(vendor_id="app", nodes=[node("a")], edges=[])
    with pytest.raises(ValueError, match="not in graph"):
        split.split_graph(graph, {"ghost"}, "x")
