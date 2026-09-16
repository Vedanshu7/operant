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

import operant.server.deps as sdeps
import tests.support.server as server
import tests.support.settings as tssettin

_AUTH = {"Authorization": f"Bearer {server.TOKEN}"}


def _build(
    root: pathlib.Path, *, approval_timeout_s: float = 300.0
) -> Tuple[Any, str]:
    import pydantic

    import operant.server.app as saapp

    settings = tssettin.test_settings(root)
    settings.approval.timeout_s = approval_timeout_s
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


def test_cancelling_a_run_waiting_for_approval_ends_it_cancelled(
    tmp_path: pathlib.Path,
) -> None:
    app, capability_id = _build(tmp_path)
    with starlette.testclient.TestClient(app) as client:
        run_id = client.post(
            "/api/v1/runs/replay",
            headers=_AUTH,
            json={"capability_id": capability_id},
        ).json()["id"]
        _poll(client, run_id, {"waiting_approval"})
        cancelled = client.post(f"/api/v1/runs/{run_id}/cancel", headers=_AUTH)
        assert cancelled.status_code == 200
        final = _poll(client, run_id, {"cancelled", "failed", "succeeded"})
        assert final["status"] == "cancelled"


def test_memory_is_listed_read_only(tmp_path: pathlib.Path) -> None:
    app, _ = _build(tmp_path)
    with starlette.testclient.TestClient(app) as client:
        empty = client.get("/api/v1/memory", headers=_AUTH)
        assert empty.status_code == 200
        assert empty.json() == {
            "plans": [],
            "lessons": [],
            "tools": [],
            "remedies": [],
        }
        assert client.get("/api/v1/memory").status_code == 401


def test_ids_that_are_not_plain_names_are_refused(tmp_path: pathlib.Path) -> None:
    app, _ = _build(tmp_path)
    with starlette.testclient.TestClient(app) as client:
        for path, body in (
            ("/api/v1/runs/discovery", {"goal": "g", "capability_id": "../x"}),
            ("/api/v1/runs/replay", {"capability_id": "../../x"}),
        ):
            refused = client.post(path, headers=_AUTH, json=body)
            assert refused.status_code == 422
        assert not (tmp_path / "x").exists()
        hidden = client.get("/api/v1/capabilities/..%2Fpolicies", headers=_AUTH)
        assert hidden.status_code in {404, 422}


def test_the_base_profiles_cannot_be_overwritten(tmp_path: pathlib.Path) -> None:
    app, _ = _build(tmp_path)
    with starlette.testclient.TestClient(app) as client:
        profile = client.get("/api/v1/profiles/p", headers=_AUTH).json()
        for reserved in ("gateway", "discovery-base"):
            profile["vendor_id"] = reserved
            refused = client.put(
                f"/api/v1/profiles/{reserved}", headers=_AUTH, json=profile
            )
            assert refused.status_code == 422


def test_an_approval_answered_after_its_timeout_is_not_found(
    tmp_path: pathlib.Path,
) -> None:
    app, capability_id = _build(tmp_path, approval_timeout_s=0.2)
    with starlette.testclient.TestClient(app) as client:
        run_id = client.post(
            "/api/v1/runs/replay",
            headers=_AUTH,
            json={"capability_id": capability_id},
        ).json()["id"]
        approval_id = _poll(client, run_id, {"waiting_approval"})[
            "pending_approval"
        ]["id"]
        _poll(client, run_id, {"failed", "escalated", "succeeded"})
        late = client.post(
            f"/api/v1/approvals/{approval_id}",
            headers=_AUTH,
            json={"approved": True, "remember": "once"},
        )
        assert late.status_code == 404


def test_a_finished_run_leaves_no_live_state(tmp_path: pathlib.Path) -> None:
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
            json={"approved": True, "remember": "once"},
        )
        _poll(client, run_id, {"succeeded", "failed", "escalated"})
        manager = getattr(app.state, sdeps._STATE_ATTR).manager
        deadline = time.monotonic() + 2.0
        while run_id in manager._handles and time.monotonic() < deadline:
            time.sleep(0.01)
        assert run_id not in manager._handles
        assert run_id not in manager._seq
        events = client.get(f"/api/v1/runs/{run_id}/events", headers=_AUTH)
        seqs = [
            int(line.split(":", 1)[1])
            for line in events.text.splitlines()
            if line.startswith("id:")
        ]
        assert seqs == sorted(seqs) == list(range(len(seqs)))


def test_every_error_is_problem_json(tmp_path: pathlib.Path) -> None:
    app, _ = _build(tmp_path)
    with starlette.testclient.TestClient(app) as client:
        responses = {
            401: client.get("/api/v1/health"),
            404: client.get("/api/v1/runs/nope", headers=_AUTH),
            422: client.post("/api/v1/runs/replay", headers=_AUTH, json={}),
        }
        for status, answered in responses.items():
            assert answered.status_code == status
            assert answered.headers["content-type"] == "application/problem+json"
            body = answered.json()
            assert body["status"] == status
            assert body["detail"]
