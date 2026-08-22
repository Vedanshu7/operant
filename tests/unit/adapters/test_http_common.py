import pathlib
from typing import Dict, Optional

import fastapi
import fastapi.testclient as testclie

import operant.adapters.http.common as common
import operant.domain.errors as errors


def _app(token: Optional[str]) -> fastapi.FastAPI:
    app = fastapi.FastAPI()
    common.install_error_handlers(app)
    router = fastapi.APIRouter(
        dependencies=[fastapi.Depends(common.bearer_dependency(token))]
    )

    @router.get("/ok")
    def _ok() -> Dict[str, bool]:
        return {"ok": True}

    @router.get("/missing")
    def _missing() -> None:
        raise errors.NotFoundError("no such thing")

    @router.get("/boom")
    def _boom() -> None:
        raise errors.DriverError("daemon down")

    app.include_router(router)
    return app


def test_bearer_is_required_when_configured() -> None:
    client = testclie.TestClient(_app("s3cret"))
    assert client.get("/ok").status_code == 401
    assert (
        client.get("/ok", headers={"Authorization": "Bearer nope"}).status_code
        == 401
    )
    response = client.get("/ok", headers={"Authorization": "Bearer s3cret"})
    assert response.status_code == 200 and response.json() == {"ok": True}


def test_no_token_disables_the_check() -> None:
    assert testclie.TestClient(_app(None)).get("/ok").status_code == 200


def test_operant_errors_become_problem_json() -> None:
    client = testclie.TestClient(_app(None))
    missing = client.get("/missing")
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/problem+json")
    body = missing.json()
    assert body["title"] == "NotFoundError" and body["detail"] == "no such thing"
    assert body["type"].endswith("errors.NotFoundError")
    assert client.get("/boom").status_code == 502


def test_ensure_token_persists_a_generated_token(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "state" / "server-token"
    first = common.ensure_token(path, None)
    assert len(first) > 30 and path.read_text().strip() == first
    assert common.ensure_token(path, None) == first
    assert common.ensure_token(path, "configured") == "configured"
