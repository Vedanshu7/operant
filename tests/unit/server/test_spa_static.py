"""
UI serving tests.

Client-side routes get index.html, while API paths and missing assets
still 404.
"""

from __future__ import annotations

import pathlib

import fastapi
import fastapi.testclient

import operant.server.app as saapp


def _client(tmp_path: pathlib.Path) -> fastapi.testclient.TestClient:
    (tmp_path / "index.html").write_text("<html>operant ui</html>")
    (tmp_path / "app.js").write_text("console.log(1)")
    app = fastapi.FastAPI()
    app.mount("/", saapp.SpaStaticFiles(directory=tmp_path, html=True), name="ui")
    return fastapi.testclient.TestClient(app)


def test_client_routes_get_the_index(tmp_path: pathlib.Path) -> None:
    client = _client(tmp_path)
    for route in ("/", "/login", "/runs/run-1"):
        response = client.get(route)
        assert response.status_code == 200, route
        assert "operant ui" in response.text


def test_assets_are_served_and_missing_ones_404(tmp_path: pathlib.Path) -> None:
    client = _client(tmp_path)
    assert client.get("/app.js").status_code == 200
    assert client.get("/missing.js").status_code == 404


def test_unknown_api_paths_are_not_answered_with_the_ui(
    tmp_path: pathlib.Path,
) -> None:
    assert _client(tmp_path).get("/api/v1/nope").status_code == 404


def test_the_index_is_revalidated_so_a_rebuilt_ui_shows_at_once(
    tmp_path: pathlib.Path,
) -> None:
    client = _client(tmp_path)
    for route in ("/", "/runs/run-1"):
        assert client.get(route).headers["cache-control"] == "no-cache", route
    assert "cache-control" not in client.get("/app.js").headers
