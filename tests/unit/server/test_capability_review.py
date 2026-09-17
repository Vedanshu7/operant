"""
Approving a capability through the API is a real review of its unknown steps.
"""

from __future__ import annotations

import pathlib
from typing import Any, Dict, Tuple

import pydantic
import starlette.testclient

import operant.infra.repositories.artifacts as raartifa
import operant.infra.repositories.graphs as rggraphs
import operant.server.app as saapp
import tests.support.server as server
import tests.support.settings as tssettin

_AUTH = {"Authorization": f"Bearer {server.TOKEN}"}


def _app(root: pathlib.Path, *, risk: str = "unknown") -> Tuple[Any, str]:
    """
    Seed a capability whose one step has ``risk``.
    """
    settings = tssettin.test_settings(root)
    settings.server.auth_token = pydantic.SecretStr(server.TOKEN)
    settings.server.cors_origins = []
    capability_id = server.seed(settings)
    graphs = rggraphs.FileGraphRepository(settings.paths.graphs_dir)
    artifacts = raartifa.FileArtifactRepository(settings.paths.artifacts_dir)
    pinned = graphs.get("app")
    marked = pinned.model_copy(
        update={"edges": [pinned.edges[0].model_copy(update={"risk": risk})]}
    )
    saved = graphs.save_new_version(marked)
    artifacts.save_new_version(
        artifacts.get(capability_id).model_copy(
            update={
                "graph_version": saved.graph_version,
                "compiled_path": ["e1"],
                "vendor_id": "app",
            }
        )
    )
    return (
        saapp.create_app(
            settings, context_factory=server.ScriptedFactory(settings)
        ),
        capability_id,
    )


def _approve(client: Any, capability_id: str, **body: Any) -> Any:
    return client.post(
        f"/api/v1/capabilities/{capability_id}/approve",
        headers=_AUTH,
        json={"force": True, **body},
    )


def _detail(client: Any, capability_id: str) -> Dict[str, Any]:
    reply = client.get(f"/api/v1/capabilities/{capability_id}", headers=_AUTH)
    return dict(reply.json())


def test_the_gate_still_applies_without_force(tmp_path: pathlib.Path) -> None:
    app, capability_id = _app(tmp_path)
    with starlette.testclient.TestClient(app) as client:
        reply = client.post(
            f"/api/v1/capabilities/{capability_id}/approve",
            headers=_AUTH,
            json={},
        )
    assert reply.status_code == 409
    assert "stability" in reply.json()["detail"]


def test_approval_lists_the_steps_a_person_has_not_seen(
    tmp_path: pathlib.Path,
) -> None:
    app, capability_id = _app(tmp_path)
    with starlette.testclient.TestClient(app) as client:
        steps = _detail(client, capability_id)["unknown_steps"]
        reply = _approve(client, capability_id)
    assert [s["edge"] for s in steps] == ["e1"]
    assert not steps[0]["reviewed"]
    assert reply.status_code == 409
    assert "review these steps" in reply.json()["detail"]


def test_force_never_skips_the_review(tmp_path: pathlib.Path) -> None:
    app, capability_id = _app(tmp_path)
    with starlette.testclient.TestClient(app) as client:
        assert _approve(client, capability_id, force=True).status_code == 409


def test_a_review_from_another_graph_version_does_not_count(
    tmp_path: pathlib.Path,
) -> None:
    app, capability_id = _app(tmp_path)
    with starlette.testclient.TestClient(app) as client:
        reply = _approve(
            client, capability_id, reviewed_edges=["e1"], graph_version=999
        )
    assert reply.status_code == 409


def test_a_covered_list_approves_and_records_the_review(
    tmp_path: pathlib.Path,
) -> None:
    app, capability_id = _app(tmp_path)
    with starlette.testclient.TestClient(app) as client:
        pinned = _detail(client, capability_id)["graph_version"]
        reply = _approve(
            client, capability_id, reviewed_edges=["e1"], graph_version=pinned
        )
        after = _detail(client, capability_id)
    assert reply.status_code == 200
    assert after["status"] == "approved"
    assert after["unknown_steps"][0]["reviewed"]


def test_a_capability_with_nothing_unknown_needs_no_list(
    tmp_path: pathlib.Path,
) -> None:
    app, capability_id = _app(tmp_path, risk="safe")
    with starlette.testclient.TestClient(app) as client:
        assert _approve(client, capability_id).status_code == 200


def test_repin_is_a_no_op_on_the_newest_version(tmp_path: pathlib.Path) -> None:
    app, capability_id = _app(tmp_path)
    with starlette.testclient.TestClient(app) as client:
        reply = client.post(
            f"/api/v1/capabilities/{capability_id}/repin", headers=_AUTH
        )
    assert reply.status_code == 200
    assert reply.json()["status"] == "draft"
