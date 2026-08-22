"""
End-to-end operator API: a replay blocks on approval and resumes.

These exercise the real app (auth, run manager, worker threads, SSE
index) over a scripted surface, proving that permissions flow through
the HTTP layer exactly as the operator UI drives them.
"""

from __future__ import annotations

import pathlib
import time
from typing import Any, Dict, Set, Tuple

import starlette.testclient

import tests.support.server as server
import tests.support.settings as tssettin

_AUTH = {"Authorization": f"Bearer {server.TOKEN}"}


def _build(root: pathlib.Path) -> Tuple[Any, str]:
    import pydantic
    import operant.server.app as saapp

    settings = tssettin.test_settings(root)
    settings.server.auth_token = pydantic.SecretStr(server.TOKEN)
    settings.server.cors_origins = []
    capability_id = server.seed(settings)
    app = saapp.create_app(
        settings, context_factory=server.ScriptedFactory(settings)
    )
    return app, capability_id


def _poll(
    client: starlette.testclient.TestClient, run_id: str, want: Set[str]
) -> Dict[str, Any]:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        detail = client.get(f"/api/v1/runs/{run_id}", headers=_AUTH).json()
        if detail["status"] in want:
            return detail
        time.sleep(0.02)
    raise AssertionError(f"run stuck at {detail['status']!r}, wanted {want}")


def test_health_requires_token(tmp_path: pathlib.Path) -> None:
    app, _ = _build(tmp_path)
    with starlette.testclient.TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/api/v1/health").status_code == 401
        ok = client.get("/api/v1/health", headers=_AUTH)
        assert ok.status_code == 200
        assert ok.json()["ok"] is True


def test_replay_blocks_on_approval_then_succeeds(tmp_path: pathlib.Path) -> None:
    app, capability_id = _build(tmp_path)
    with starlette.testclient.TestClient(app) as client:
        started = client.post(
            "/api/v1/runs/replay",
            headers=_AUTH,
            json={"capability_id": capability_id},
        )
        assert started.status_code == 200
        run_id = started.json()["id"]
        detail = _poll(client, run_id, {"waiting_approval"})
        approval = detail["pending_approval"]
        assert approval is not None
        assert approval["kind"] == "mutating"
        answered = client.post(
            f"/api/v1/approvals/{approval['id']}",
            headers=_AUTH,
            json={"approved": True, "remember": "once"},
        )
        assert answered.status_code == 200
        final = _poll(client, run_id, {"succeeded", "failed", "escalated"})
        assert final["status"] == "succeeded"
        events = client.get(f"/api/v1/runs/{run_id}/events", headers=_AUTH)
        assert events.status_code == 200
        assert "approval_requested" in events.text


def test_denied_approval_fails_the_run(tmp_path: pathlib.Path) -> None:
    app, capability_id = _build(tmp_path)
    with starlette.testclient.TestClient(app) as client:
        run_id = client.post(
            "/api/v1/runs/replay",
            headers=_AUTH,
            json={"capability_id": capability_id},
        ).json()["id"]
        detail = _poll(client, run_id, {"waiting_approval"})
        client.post(
            f"/api/v1/approvals/{detail['pending_approval']['id']}",
            headers=_AUTH,
            json={"approved": False, "remember": "once"},
        )
        final = _poll(client, run_id, {"failed", "escalated", "succeeded"})
        assert final["status"] == "failed"


def test_list_runs_and_unknown_run(tmp_path: pathlib.Path) -> None:
    app, capability_id = _build(tmp_path)
    with starlette.testclient.TestClient(app) as client:
        client.post(
            "/api/v1/runs/replay",
            headers=_AUTH,
            json={"capability_id": capability_id},
        )
        listed = client.get("/api/v1/runs", headers=_AUTH).json()
        assert len(listed["items"]) == 1
        missing = client.get("/api/v1/runs/nope", headers=_AUTH)
        assert missing.status_code == 404
