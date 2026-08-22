"""Plumbing shared by the operator server and the driver daemon.

Bearer-token authentication, a problem+json error envelope for every
``OperantError``, and the health payload. Both FastAPI apps install these so
clients see one contract.

Typical usage example:

  app = fastapi.FastAPI()
  install_error_handlers(app)
  router = fastapi.APIRouter(dependencies=[bearer_dependency(token)])

Import as:

import operant.adapters.http.common as common
"""

from __future__ import annotations

import collections.abc
import pathlib
import secrets
from typing import Final, Optional, Tuple

import fastapi
import fastapi.responses as response
import pydantic

import operant
import operant.domain.errors as errors
import operant.helpers.files as files

_STATUS_BY_ERROR: Final[Tuple[Tuple[type[Exception], int], ...]] = (
    (errors.NotFoundError, 404),
    (errors.UnknownApprovalError, 404),
    (errors.UnknownInterventionError, 404),
    (errors.PolicyViolationError, 403),
    (errors.ApprovalRequiredError, 428),
    (errors.ApprovalDeniedError, 403),
    (errors.InvalidTransitionError, 409),
    (errors.VersionConflictError, 409),
    (errors.PreconditionFailedError, 422),
    (errors.ConfigError, 422),
    (errors.SecretBackendUnavailableError, 503),
    (errors.DriverError, 502),
    (errors.SurfaceError, 502),
)


# #############################################################################
# Problem
# #############################################################################


class Problem(pydantic.BaseModel):
    """
    RFC 9457-style error body.

    :ivar type: Dotted error class name, stable for clients to switch
        on.
    :ivar title: Short human-readable summary.
    :ivar status: HTTP status code.
    :ivar detail: The exception message.
    """

    type: str
    title: str
    status: int
    detail: str


# #############################################################################
# HealthResponse
# #############################################################################


class HealthResponse(pydantic.BaseModel):
    """
    Liveness payload.

    :ivar ok: Whether the process considers itself healthy.
    :ivar version: Package version.
    :ivar protocol: Wire protocol version, for the driver daemon.
    """

    ok: bool = True
    version: str = operant.__version__
    protocol: Optional[str] = None


def status_for(error: Exception) -> int:
    """
    Map an exception to the HTTP status it should produce.
    """
    result = 500
    for error_type, status in _STATUS_BY_ERROR:
        if isinstance(error, error_type):
            result = status
            break
    return result


def problem_response(error: Exception) -> response.JSONResponse:
    """
    Render an exception as a problem+json response.
    """
    status = status_for(error)
    body = Problem(
        type=f"{type(error).__module__}.{type(error).__name__}",
        title=type(error).__name__,
        status=status,
        detail=str(error),
    )
    rendered = response.JSONResponse(
        status_code=status,
        content=body.model_dump(),
        media_type="application/problem+json",
    )
    return rendered


def install_error_handlers(app: fastapi.FastAPI) -> None:
    """
    Register the ``OperantError`` → problem+json handler on ``app``.
    """

    @app.exception_handler(errors.OperantError)
    async def _handle(
        _request: fastapi.Request, error: errors.OperantError
    ) -> response.JSONResponse:
        return problem_response(error)


def bearer_dependency(
    expected: Optional[str],
) -> collections.abc.Callable[..., None]:
    """
    Build a dependency that enforces ``Authorization: Bearer <token>``.

    :param expected: The token to require; ``None`` disables the check,
        which is only acceptable for loopback-only development.
    :return: A FastAPI dependency.
    """

    def _check(
        authorization: Optional[str] = fastapi.Header(default=None),
    ) -> None:
        if expected is None:
            return
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(
            token, expected
        ):
            raise fastapi.HTTPException(
                status_code=401,
                detail="missing or invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return _check


def ensure_token(path: pathlib.Path, configured: Optional[str]) -> str:
    """
    Return the configured token, or a persisted generated one.

    :param path: Where to keep a generated token between starts.
    :param configured: The token from settings, if any.
    :return: The token every client must present.
    """
    if configured:
        # Prefer an explicitly configured token.
        token = configured
    else:
        # Otherwise reuse a persisted token or mint a new one.
        stored = ""
        if path.exists():
            stored = path.read_text(encoding="utf-8").strip()
        if stored:
            # Reuse the token persisted from a previous start.
            token = stored
        else:
            # Mint a new token and persist it for next time.
            token = secrets.token_urlsafe(32)
            files.write_text(path, token + "\n")
            path.chmod(0o600)
    return token
