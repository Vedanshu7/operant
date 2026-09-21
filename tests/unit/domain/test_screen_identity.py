"""
Screen identity says how sure it is, and survives a UI change.
"""

from __future__ import annotations

import re
from typing import List, Optional, Sequence

import pytest

import operant.domain.fingerprint as odfinger
import operant.domain.graph.localize as localize
import operant.domain.graph.merge as merge
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import tests.support.screens as screens


def _control(role: str, name: str, path: str) -> digest.Control:
    return screens.control(role=role, name=name, path=path)


MENU = (
    _control("link", "Home", "content>nav>link"),
    _control("link", "Log Out", "content>nav>link"),
    _control("link", "Accounts", "content>nav>link"),
)
ACCOUNTS = MENU + (
    _control("heading", "Accounts", "content>main>heading"),
    _control("link", "Details", "content>main>table>row>link"),
)
TRANSFER = MENU + (
    _control("text_field", "Amount", "content>main>form>text_field"),
    _control("button", "Send", "content>main>form>button"),
)


def _screen(
    controls: Sequence[digest.Control],
    title: str,
    url: Optional[str] = None,
) -> digest.ScreenDigest:
    return digest.ScreenDigest(
        app="App", window_title=title, text="", controls=tuple(controls), url=url
    )


def _node(
    node_id: str,
    controls: Sequence[digest.Control],
    title: str,
    url_paths: Optional[List[str]] = None,
) -> graph.Node:
    return graph.Node(
        id=node_id,
        description=title,
        checks=[graph.TitleMatches(pattern=re.escape(title))],
        fingerprint=odfinger.of(_screen(controls, title)),
        url_paths=url_paths or [],
    )


def _graph(*nodes: graph.Node) -> graph.AppGraph:
    return graph.AppGraph(vendor_id="v", nodes=list(nodes))


APP = _graph(
    _node("accounts", ACCOUNTS, "Accounts", ["/accounts"]),
    _node("transfer", TRANSFER, "Transfer", ["/transfer"]),
)


def test_a_clean_screen_is_a_match() -> None:
    found = localize.locate(_screen(ACCOUNTS, "Accounts"), APP)
    assert (found.kind, found.node_id) == ("match", "accounts")
    assert found.confirmed == "accounts"


def test_shared_navigation_identifies_nothing() -> None:
    found = localize.locate(_screen(MENU, "Home"), APP)
    assert found.kind == "ambiguous"
    assert found.confirmed is None


def test_a_look_alike_with_the_content_but_not_the_title_has_drifted() -> None:
    found = localize.locate(_screen(ACCOUNTS, "Home"), APP)
    assert (found.kind, found.node_id) == ("drifted", "accounts")
    assert found.confirmed is None


def test_a_url_can_veto_a_match_but_never_make_one() -> None:
    wrong = _screen(ACCOUNTS, "Accounts", "https://bank.test/transfer")
    assert localize.locate(wrong, APP).kind == "drifted"
    right = _screen(MENU, "Home", "https://bank.test/accounts")
    assert localize.locate(right, APP).confirmed is None


def test_a_screen_with_both_identities_is_ambiguous() -> None:
    found = localize.locate(_screen(ACCOUNTS + TRANSFER[3:], "Mixed"), APP)
    assert found.kind == "ambiguous"
    assert found.candidates == ("accounts", "transfer")


def test_the_path_settles_a_tie_and_nothing_else() -> None:
    mixed = _screen(ACCOUNTS + TRANSFER[3:], "Transfer")
    found = localize.locate(mixed, APP, expected="transfer")
    assert (found.kind, found.node_id) == ("match", "transfer")
    assert (
        localize.locate(_screen(MENU, "Home"), APP, expected="transfer").confirmed
        is None
    )


def test_translation_keeps_the_structure_view() -> None:
    translated = [
        _control(c.role, f"translated {i}", c.path)
        for i, c in enumerate(ACCOUNTS)
    ]
    found = localize.locate(_screen(translated, "Accounts"), APP)
    assert (found.kind, found.node_id, found.basis) == (
        "match",
        "accounts",
        "identity",
    )


def test_a_redesign_keeps_the_text_view() -> None:
    moved = [_control(c.role, c.name, f"new>{c.path}") for c in ACCOUNTS]
    found = localize.locate(_screen(moved, "Accounts"), APP)
    assert (found.kind, found.node_id, found.basis) == (
        "match",
        "accounts",
        "identity",
    )


def test_losing_both_views_with_the_title_intact_has_drifted() -> None:
    rebuilt = [_control("group", "new page", "new>group")]
    found = localize.locate(_screen(rebuilt, "Accounts"), APP)
    assert (found.kind, found.node_id, found.basis) == (
        "drifted",
        "accounts",
        "checks",
    )


def test_losing_everything_is_unknown_rather_than_a_guess() -> None:
    rebuilt = [_control("group", "new page", "new>group")]
    assert localize.locate(_screen(rebuilt, "Elsewhere"), APP).kind == "unknown"


def test_a_partial_graph_never_claims_a_clean_look_alike() -> None:
    partial = _graph(
        _node("accounts", ACCOUNTS, "Accounts"),
        graph.Node(
            id="home",
            description="Home",
            checks=[graph.TitleMatches(pattern="Home")],
        ),
    )
    found = localize.locate(_screen(ACCOUNTS, "Home"), partial)
    assert (found.kind, found.node_id) == ("drifted", "accounts")


@pytest.mark.parametrize(
    "url, expected",
    [
        (None, ""),
        ("https://a.test/parabank/overview.htm", "/parabank/overview.htm"),
        ("https://a.test/activity.htm?id=13344", "/activity.htm"),
        ("https://a.test/x.htm;jsessionid=ABC123", "/x.htm"),
        ("https://a.test/users/12345/edit/", "/users/#/edit"),
        ("https://a.test/app#/orders/9", "/app#/orders/#"),
        ("https://a.test/page#section", "/page"),
        ("https://a.test", "/"),
    ],
)
def test_a_url_is_reduced_to_a_value_free_path(url, expected) -> None:
    assert odfinger.url_path(url) == expected


def _edge(
    edge_id: str, start: str, end_or_name: str, name: str = ""
) -> graph.Edge:
    return graph.Edge.model_validate(
        {
            "id": edge_id,
            "from": start,
            "to": end_or_name if name else start,
            "description": name or end_or_name,
            "action": {"kind": "click"},
            "target": {
                "strategies": [
                    {"kind": "role", "role": "link", "name": name or end_or_name}
                ],
                "reasoning": "r",
            },
        }
    )


def test_merge_keeps_two_states_that_share_a_title_apart() -> None:
    base = _graph(_node("out", TRANSFER, "Welcome"), _node("x", MENU, "X"))
    logged_in = _node("in", ACCOUNTS[3:], "Welcome")
    merged, changed, remap, _ = merge.merge_recording(
        base, "v", [logged_in], [], []
    )
    assert changed
    assert remap["in"] != "out"
    assert len(merged.nodes) == 3


def test_merge_reuses_a_screen_it_already_knows() -> None:
    base = _graph(_node("out", TRANSFER, "Welcome"), _node("x", MENU, "X"))
    again = _node("again", TRANSFER, "Welcome", ["/welcome"])
    merged, _, remap, _ = merge.merge_recording(base, "v", [again], [], [])
    assert remap["again"] == "out"
    assert merged.node("out").url_paths == ["/welcome"]


def test_a_different_state_cannot_write_onto_a_node_without_a_fingerprint() -> (
    None
):
    bare = graph.Node(
        id="home",
        description="Home",
        checks=[graph.TitleMatches(pattern="Welcome")],
    )
    base = graph.AppGraph(
        vendor_id="v", nodes=[bare], edges=[_edge("e1", "home", "Log In")]
    )
    logged_in = _node("in", ACCOUNTS, "Welcome")
    merged, _, remap, _ = merge.merge_recording(
        base, "v", [logged_in], [_edge("e2", "in", "Details")], []
    )
    assert remap["in"] != "home"
    assert merged.node("home").fingerprint == []


def test_a_recording_that_leaves_the_same_way_fills_in_the_fingerprint() -> None:
    bare = graph.Node(
        id="home",
        description="Home",
        checks=[graph.TitleMatches(pattern="Welcome")],
    )
    base = graph.AppGraph(
        vendor_id="v", nodes=[bare], edges=[_edge("e1", "home", "Log In")]
    )
    same = _node("again", TRANSFER, "Welcome")
    merged, _, remap, _ = merge.merge_recording(
        base, "v", [same], [_edge("e2", "again", "Log In")], []
    )
    assert remap["again"] == "home"
    assert merged.node("home").fingerprint


def test_a_stranded_node_does_not_hold_identity_back() -> None:
    bare = graph.Node(
        id="stranded",
        description="old mistake",
        checks=[graph.TitleMatches(pattern="Oops")],
    )
    link = _edge("e1", "accounts", "transfer", "Send money")
    dead = _edge("e2", "stranded", "accounts", "Old").model_copy(
        update={"retired_in": 2}
    )
    app = graph.AppGraph(
        vendor_id="v", nodes=[*APP.nodes, bare], edges=[link, dead]
    )
    found = localize.locate(_screen(ACCOUNTS, "Accounts"), app)
    assert (found.kind, found.basis) == ("match", "identity")


def test_a_reachable_node_without_a_fingerprint_keeps_identity_off() -> None:
    bare = graph.Node(
        id="reachable",
        description="new",
        checks=[graph.TitleMatches(pattern="New")],
    )
    link = _edge("e1", "accounts", "reachable", "Open")
    app = graph.AppGraph(vendor_id="v", nodes=[*APP.nodes, bare], edges=[link])
    assert localize.locate(_screen(ACCOUNTS, "Accounts"), app).basis == "coverage"
