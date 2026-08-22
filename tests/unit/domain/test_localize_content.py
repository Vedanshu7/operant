"""
Content-addressed localization separates states that share a title.
"""

from __future__ import annotations

import operant.domain.fingerprint as odfinger
import operant.domain.graph.localize as localize
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph


def _box() -> digest.Box:
    return digest.Box(x=0.0, y=0.0, w=0.1, h=0.1)


def _control(role: str, name: str, path: str):
    return digest.Control(
        ref="r", role=role, name=name, label="", path=path, box=_box()
    )


_LOGIN = (
    _control("textfield", "Username", "content>form>textfield"),
    _control("textfield", "Password", "content>form>textfield"),
    _control("button", "Log In", "content>form>button"),
)
_OVERVIEW = (
    _control("link", "Accounts Overview", "content>menu>link"),
    _control("link", "Log Out", "content>menu>link"),
)


def _screen(controls) -> digest.ScreenDigest:
    # Both states keep the same "Welcome" title, as ParaBank's index does.
    return digest.ScreenDigest(
        app="Chrome", window_title="Welcome", text="", controls=controls
    )


def _node(node_id: str, controls) -> graph.Node:
    return graph.Node(
        id=node_id,
        description=node_id,
        checks=[graph.TitleMatches(pattern="Welcome")],
        fingerprint=odfinger.of(_screen(controls)),
    )


def _graph() -> graph.AppGraph:
    return graph.AppGraph(
        graph_id="parabank",
        vendor_id="parabank",
        app_name="Chrome",
        window_title_pattern="Welcome",
        graph_version=1,
        nodes=[_node("login", _LOGIN), _node("overview", _OVERVIEW)],
        edges=[],
    )


def test_locates_by_content_when_titles_collide() -> None:
    app_graph = _graph()
    assert localize.locate(_screen(_LOGIN), app_graph) == "login"
    assert localize.locate(_screen(_OVERVIEW), app_graph) == "overview"


def test_old_graph_without_fingerprints_falls_back_to_checks() -> None:
    app_graph = graph.AppGraph(
        graph_id="parabank",
        vendor_id="parabank",
        app_name="Chrome",
        window_title_pattern="Welcome",
        graph_version=1,
        nodes=[
            graph.Node(
                id="only",
                description="only",
                checks=[graph.TitleMatches(pattern="Welcome")],
            )
        ],
        edges=[],
    )
    assert localize.locate(_screen(_LOGIN), app_graph) == "only"
