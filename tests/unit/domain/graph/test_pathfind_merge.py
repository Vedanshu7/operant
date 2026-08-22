"""
Localize, pathfind, and merge over the application graph.
"""

from __future__ import annotations

import importlib
import importlib.util
import re
import sys
import types
from typing import Any, List, Optional, Tuple

import pytest

import operant.domain.graph.merge as merge
import operant.domain.graph.pathfind as pathfind
import operant.domain.models.digest as mddigest
import operant.domain.models.graph as mggraph

_LOCALIZE = "operant.domain.graph.localize"


def _stub_params() -> types.ModuleType:
    module = types.ModuleType("operant.domain.params")

    def substitute_condition(condition: Any, values: Any) -> Any:
        return condition

    module.substitute_condition = substitute_condition  # type: ignore[attr-defined]
    return module


def _stub_outcomes() -> types.ModuleType:
    module = types.ModuleType("operant.domain.outcomes")

    def evaluate(condition: Any, screen: Any) -> bool:
        if condition.kind == "titleMatches":
            return (
                re.search(condition.pattern, screen.window_title, re.I)
                is not None
            )
        if condition.kind == "textMatches":
            return re.search(condition.pattern, screen.text, re.I) is not None
        return False

    def on_node(checks: Any, screen: Any) -> bool:
        return all(evaluate(c, screen) for c in checks)

    module.on_node = on_node  # type: ignore[attr-defined]
    return module


@pytest.fixture
def localize(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    # The sibling modules are being written concurrently; stub only the
    # two functions ``locate`` calls when they are not importable yet.
    stubs = {
        "operant.domain.params": _stub_params,
        "operant.domain.outcomes": _stub_outcomes,
    }
    for name, build in stubs.items():
        if importlib.util.find_spec(name) is None:
            monkeypatch.setitem(sys.modules, name, build())
    monkeypatch.delitem(sys.modules, _LOCALIZE, raising=False)
    return importlib.import_module(_LOCALIZE)


def node(
    nid: str, pattern: str, extra: Optional[List[Any]] = None
) -> mggraph.Node:
    checks = [mggraph.TitleMatches(pattern=pattern), *(extra or [])]
    return mggraph.Node(id=nid, description=nid, checks=checks)


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


def digest(title: str, text: str = "") -> mddigest.ScreenDigest:
    return mddigest.ScreenDigest(
        app="Chrome", window_title=title, text=text, controls=()
    )


def test_localize_matches_by_checks(localize: types.ModuleType) -> None:
    g = mggraph.AppGraph(
        vendor_id="v",
        nodes=[node("login", "Welcome"), node("overview", "Accounts Overview")],
    )
    assert (
        localize.locate(digest("ParaBank | Accounts Overview - Chrome"), g)
        == "overview"
    )
    assert localize.locate(digest("ParaBank | Welcome - Chrome"), g) == "login"


def test_localize_returns_none_when_no_node_matches(
    localize: types.ModuleType,
) -> None:
    g = mggraph.AppGraph(vendor_id="v", nodes=[node("login", "Welcome")])
    assert localize.locate(digest("Totally Different Page"), g) is None


def test_localize_prefers_most_specific_node(
    localize: types.ModuleType,
) -> None:
    generic = node("generic", "ParaBank")
    specific = node(
        "detail",
        "ParaBank",
        extra=[mggraph.TitleMatches(pattern="Account Activity")],
    )
    g = mggraph.AppGraph(vendor_id="v", nodes=[generic, specific])
    # Both match, but the 2-check node wins.
    assert (
        localize.locate(digest("ParaBank | Account Activity - Chrome"), g)
        == "detail"
    )


def test_shortest_path_simple_chain() -> None:
    g = mggraph.AppGraph(
        vendor_id="v",
        nodes=[node("a", "A"), node("b", "B"), node("c", "C")],
        edges=[edge("e1", "a", "b"), edge("e2", "b", "c")],
    )
    path = pathfind.shortest_path(g, "a", "c")
    assert path is not None
    assert [e.id for e in path] == ["e1", "e2"]


def test_shortest_path_from_the_middle() -> None:
    g = mggraph.AppGraph(
        vendor_id="v",
        nodes=[node("a", "A"), node("b", "B"), node("c", "C")],
        edges=[edge("e1", "a", "b"), edge("e2", "b", "c")],
    )
    # Starting at b (mid-graph) leaves only the remaining hop.
    path = pathfind.shortest_path(g, "b", "c")
    assert path is not None
    assert [e.id for e in path] == ["e2"]


def test_shortest_path_handles_cycles_and_is_deterministic() -> None:
    g = mggraph.AppGraph(
        vendor_id="v",
        nodes=[node("a", "A"), node("b", "B"), node("c", "C")],
        edges=[
            edge("e1", "a", "b"),
            edge("back", "b", "a"),
            edge("e2", "b", "c"),
        ],
    )
    path = pathfind.shortest_path(g, "a", "c")
    assert path is not None
    assert [e.id for e in path] == ["e1", "e2"]
    assert pathfind.shortest_path(g, "a", "a") == []


def test_shortest_path_none_when_unreachable() -> None:
    g = mggraph.AppGraph(
        vendor_id="v", nodes=[node("a", "A"), node("b", "B")], edges=[]
    )
    assert pathfind.shortest_path(g, "a", "b") is None


def test_compiled_edges_none_when_id_missing() -> None:
    g = mggraph.AppGraph(
        vendor_id="v", nodes=[node("a", "A")], edges=[edge("e1", "a", "a")]
    )
    assert pathfind.compiled_edges(g, ["e1"]) is not None
    assert pathfind.compiled_edges(g, ["e1", "gone"]) is None


def _login_recording() -> Tuple[List[mggraph.Node], List[mggraph.Edge]]:
    nodes = [node("login", "Welcome"), node("overview", "Accounts Overview")]
    edges = [edge("l1", "login", "overview")]
    return nodes, edges


def test_merge_into_empty_graph_adds_all() -> None:
    nodes, edges = _login_recording()
    graph, changed, node_remap, _ = merge.merge_recording(
        None, "parabank", nodes, edges, []
    )
    assert changed is True
    assert {n.id for n in graph.nodes} == {"login", "overview"}
    assert node_remap == {"login": "login", "overview": "overview"}


def test_merge_reuses_shared_login_node() -> None:
    # First capability records login -> overview.
    base, *_ = merge.merge_recording(None, "parabank", *_login_recording(), [])
    # A second capability re-records the SAME login screen under a fresh
    # node id, then goes somewhere new.
    nodes2 = [
        node("login_again", "Welcome"),
        node("transfer", "Transfer Funds"),
    ]
    edges2 = [edge("t1", "login_again", "transfer")]
    graph, changed, node_remap, _ = merge.merge_recording(
        base, "parabank", nodes2, edges2, []
    )
    # The login screen is recognised as the existing shared node.
    assert node_remap["login_again"] == "login"
    assert (
        sum(
            1
            for n in graph.nodes
            if getattr(n.checks[0], "pattern", "") == "Welcome"
        )
        == 1
    )
    assert {n.id for n in graph.nodes} == {"login", "overview", "transfer"}
    assert changed is True


def test_merge_no_change_when_recording_already_present() -> None:
    base, *_ = merge.merge_recording(None, "parabank", *_login_recording(), [])
    _, changed, _, _ = merge.merge_recording(
        base, "parabank", *_login_recording(), []
    )
    assert changed is False


def test_merge_backfills_fingerprint_onto_older_shared_node() -> None:
    # An older graph whose shared nodes carry no content fingerprint.
    base, *_ = merge.merge_recording(None, "parabank", *_login_recording(), [])
    assert all(not n.fingerprint for n in base.nodes)
    # A new recording of the same screens now carries fingerprints.
    fp_nodes = [
        mggraph.Node(
            id="login2",
            description="login",
            checks=[mggraph.TitleMatches(pattern="Welcome")],
            fingerprint=["button|log in||form>button"],
        ),
        node("overview2", "Accounts Overview"),
    ]
    graph, changed, node_remap, _ = merge.merge_recording(
        base, "parabank", fp_nodes, [edge("l2", "login2", "overview2")], []
    )
    assert changed is True  # backfill is a graph change -> new version
    assert node_remap["login2"] == "login"
    login = next(n for n in graph.nodes if n.id == "login")
    assert login.fingerprint == ["button|log in||form>button"]


def _click_edge(eid: str, frm: str, to: str, target_name: str) -> mggraph.Edge:
    return mggraph.Edge.model_validate(
        {
            "id": eid,
            "from": frm,
            "to": to,
            "description": eid,
            "action": {"kind": "click"},
            "target": {
                "strategies": [
                    {"kind": "role", "role": "text_field", "name": target_name}
                ],
                "reasoning": "r",
            },
        }
    )


def test_merge_keeps_distinct_clicks_on_same_screen() -> None:
    # Two clicks on DIFFERENT controls of the same screen must stay
    # distinct (regression: the key used to ignore the target).
    nodes = [node("login", "Welcome")]
    edges = [
        _click_edge("c-user", "login", "login", "Username"),
        _click_edge("c-pass", "login", "login", "Password"),
    ]
    graph, changed, _, edge_remap = merge.merge_recording(
        None, "app", nodes, edges, []
    )
    assert changed is True
    click_targets = {
        getattr(e.target.strategies[0], "name", None)
        for e in graph.edges
        if e.action.kind == "click" and e.target is not None
    }
    assert click_targets == {"Username", "Password"}
    # Distinct recording edges map to distinct canonical edges.
    assert edge_remap["c-user"] != edge_remap["c-pass"]
