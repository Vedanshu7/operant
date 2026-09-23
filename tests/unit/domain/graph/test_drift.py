"""
Drift is noticed on verified arrivals, and learning needs several visits.
"""

from __future__ import annotations

import pytest

import operant.domain.errors as errors
import operant.domain.fingerprint as odfinger
import operant.domain.graph.drift as ogdrift
import operant.domain.graph.merge as merge
import operant.domain.graph.pathfind as pathfind
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import tests.support.screens as screens

CONTROLS = (
    screens.control(role="link", name="Home", path="content>nav>link"),
    screens.control(role="button", name="Send", path="content>form>button"),
)


def _screen(controls) -> digest.ScreenDigest:
    return digest.ScreenDigest(
        app="App", window_title="Page", text="", controls=tuple(controls)
    )


NODE = graph.Node(
    id="page",
    description="Page",
    checks=[graph.TitleMatches(pattern="Page")],
    fingerprint=odfinger.of(_screen(CONTROLS)),
)


def test_an_unchanged_screen_loses_nothing() -> None:
    assert ogdrift.lost_views(NODE, _screen(CONTROLS)) == []


def test_translation_loses_the_text_view_only() -> None:
    translated = [
        screens.control(role=c.role, name=f"x{i}", path=c.path)
        for i, c in enumerate(CONTROLS)
    ]
    assert ogdrift.lost_views(NODE, _screen(translated)) == ["text"]


def test_a_redesign_loses_the_structure_view_only() -> None:
    moved = [
        screens.control(role=c.role, name=c.name, path=f"new>{c.path}")
        for c in CONTROLS
    ]
    assert ogdrift.lost_views(NODE, _screen(moved)) == ["structure"]


def test_a_node_without_a_fingerprint_cannot_drift() -> None:
    bare = NODE.model_copy(update={"fingerprint": []})
    assert ogdrift.lost_views(bare, _screen(())) == []


def test_a_core_needs_enough_visits() -> None:
    assert ogdrift.stable_core([["a", "b"], ["a"]]) is None


def test_one_banner_does_not_enter_the_core() -> None:
    visits = [["a", "b", "banner"], ["a", "b"], ["a", "b"]]
    assert ogdrift.stable_core(visits) == ["a", "b"]


def test_relearning_changes_only_what_the_visits_settled() -> None:
    other = NODE.model_copy(update={"id": "other"})
    app_graph = graph.AppGraph(vendor_id="v", nodes=[NODE, other])
    learned = ogdrift.relearn(
        app_graph,
        {"page": [["a"], ["a"], ["a"]]},
        {"other": ["/other", "/other", "/other"]},
    )
    assert learned is not None
    assert learned.node("page").fingerprint == ["a"]
    assert learned.node("other").fingerprint == NODE.fingerprint
    assert learned.node("other").url_paths == ["/other"]


def test_nothing_new_changes_nothing() -> None:
    app_graph = graph.AppGraph(vendor_id="v", nodes=[NODE])
    assert ogdrift.relearn(app_graph, {}, {}) is None


def _node(node_id: str) -> graph.Node:
    return graph.Node(
        id=node_id,
        description=node_id,
        checks=[graph.TitleMatches(pattern=node_id)],
    )


def _edge(edge_id: str, start: str, end: str, name: str) -> graph.Edge:
    return graph.Edge.model_validate(
        {
            "id": edge_id,
            "from": start,
            "to": end,
            "description": name,
            "action": {"kind": "click"},
            "target": {
                "strategies": [{"kind": "role", "role": "link", "name": name}],
                "reasoning": "r",
            },
        }
    )


def _broken() -> graph.AppGraph:
    return graph.AppGraph(
        vendor_id="v",
        graph_version=4,
        nodes=[_node("a"), _node("b")],
        edges=[_edge("old", "a", "b", "Old link")],
    )


def test_a_failing_edge_retires_when_the_run_found_another_way() -> None:
    merged, changed, _, _ = merge.merge_recording(
        _broken(),
        "v",
        [_node("a"), _node("b")],
        [_edge("e1", "a", "b", "New link")],
        [],
        retire={"old"},
    )
    assert changed
    assert merged.edge("old").retired_in == 5
    route = pathfind.shortest_path(merged, "a", "b")
    assert route is not None
    assert [edge.description for edge in route] == ["New link"]
    assert [e.description for e in merged.edges_from("a")] == ["New link"]


def test_a_failing_edge_stays_when_nothing_replaced_it() -> None:
    merged, _, _, _ = merge.merge_recording(
        _broken(), "v", [_node("a")], [], [], retire={"old"}
    )
    assert merged.edge("old").retired_in is None


def test_an_edge_the_run_used_again_stays() -> None:
    merged, _, _, _ = merge.merge_recording(
        _broken(),
        "v",
        [_node("a"), _node("b")],
        [_edge("e1", "a", "b", "Old link")],
        [],
        retire={"old"},
    )
    assert merged.edge("old").retired_in is None


def test_a_redesign_is_not_intersected_with_the_old_look() -> None:
    old = ["menu", "old a", "old b", "old c"]
    new = ["menu", "new a", "new b", "new c"]
    assert ogdrift.recent_visits([old, old, new, new]) == [new, new]


def test_a_redesign_needs_three_visits_of_its_own() -> None:
    old = ["menu", "old a", "old b"]
    new = ["menu", "new a", "new b"]
    assert (
        ogdrift.stable_core(ogdrift.recent_visits([old, old, old, new])) is None
    )
    settled = ogdrift.recent_visits([old, old, new, new, new])
    assert ogdrift.stable_core(settled) == sorted(new)


def test_only_recent_visits_count() -> None:
    assert len(ogdrift.recent_visits([["a"]] * 25)) == ogdrift.MAX_VISITS


def test_an_address_seen_once_is_not_learned() -> None:
    app_graph = graph.AppGraph(vendor_id="v", nodes=[NODE])
    assert ogdrift.relearn(app_graph, {}, {"page": ["/once"]}) is None
    learned = ogdrift.relearn(app_graph, {}, {"page": ["/x", "/x", "/x"]})
    assert learned is not None
    assert learned.node("page").url_paths == ["/x"]


def test_retiring_marks_the_next_version_and_refuses_unknown_edges() -> None:
    retired = ogdrift.retire(_broken(), {"old"})
    assert retired.edge("old").retired_in == 5
    with pytest.raises(errors.NotFoundError):
        ogdrift.retire(_broken(), {"nope"})
