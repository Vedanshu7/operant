"""
The operator web server: type a goal, watch a run, answer every prompt.

``create_app`` wires the run manager, repositories, and event hub,
mounts the versioned API and the built frontend, and installs bearer
authentication and the shared problem+json error handler. The lifespan
opens the database, brings it to schema head, and binds the event hub to
the running event loop so worker threads can publish across the thread
boundary.

Import as:

import operant.server.app as saapp
"""

from __future__ import annotations

import asyncio
import collections.abc
import contextlib
from typing import Optional

import fastapi
import fastapi.middleware.cors as cors
import fastapi.staticfiles
import starlette.exceptions
import starlette.responses
import starlette.types

import operant.adapters.http.common as common
import operant.adapters.secrets.factory as sffactor
import operant.application.context as context
import operant.infra.db.engine as engine
import operant.infra.db.migrate as migrate
import operant.infra.repositories.artifacts as artifact
import operant.infra.repositories.graphs as graphs
import operant.infra.repositories.profiles as profiles
import operant.infra.repositories.runs as runs
import operant.infra.settings as issettin
import operant.server.api.catalog as catalog
import operant.server.api.hitl as hitl
import operant.server.api.runs as arruns
import operant.server.api.secrets as secrets
import operant.server.api.system as system
import operant.server.deps as deps
import operant.server.jobs.hub as jhhub
import operant.server.jobs.lease as jllease
import operant.server.jobs.manager as jmmanage

_API_PREFIX = "/api/v1"


def _resolve_token(settings: issettin.OperantSettings) -> str:
    """
    Resolve the bearer token from settings or the state directory.
    """
    configured = (
        settings.server.auth_token.get_secret_value()
        if settings.server.auth_token
        else None
    )
    token = common.ensure_token(
        settings.paths.state_dir / "server-token", configured
    )
    return token


def _build_state(
    settings: issettin.OperantSettings,
    loop: asyncio.AbstractEventLoop,
    token: str,
    factory: context.ContextBuilder,
) -> deps.ServerState:
    """
    Build the shared server state: repositories, run manager, and hub.
    """
    database = engine.Database.open(settings.paths.db_path)
    migrate.upgrade(database)
    run_repo = runs.SqlRunRepository(database)
    hub = jhhub.EventHub(loop)
    settings.paths.screen_lock.parent.mkdir(parents=True, exist_ok=True)
    lease = jllease.DriverLease(settings.paths.screen_lock)
    manager = jmmanage.RunManager(
        settings=settings,
        factory=factory,
        artifacts=artifact.FileArtifactRepository(settings.paths.artifacts_dir),
        graphs=graphs.FileGraphRepository(settings.paths.graphs_dir),
        profiles=profiles.FileProfileRepository(
            settings.paths.policies_dir, settings.paths.discovery_base_profile
        ),
        secret_store=sffactor.secret_store(settings.secrets),
        runs=run_repo,
        hub=hub,
        lease=lease,
    )
    manager.reconcile_interrupted()
    state = deps.ServerState(
        settings=settings,
        database=database,
        runs=run_repo,
        secret_refs=runs.SqlSecretRefRepository(database),
        artifacts=artifact.FileArtifactRepository(settings.paths.artifacts_dir),
        graphs=graphs.FileGraphRepository(settings.paths.graphs_dir),
        profiles=profiles.FileProfileRepository(
            settings.paths.policies_dir, settings.paths.discovery_base_profile
        ),
        secret_store=sffactor.secret_store(settings.secrets),
        manager=manager,
        hub=hub,
        lease=lease,
        token=token,
    )
    return state


# #############################################################################
# SpaStaticFiles
# #############################################################################


class SpaStaticFiles(fastapi.staticfiles.StaticFiles):
    """
    Serve the built UI, answering client-side routes with ``index.html``.

    The UI routes in the browser (``/login``, ``/runs/<id>``); without
    this fallback, opening or reloading such a URL returned 404. API
    paths and missing assets (anything with a file extension) still 404.

    Pages are revalidated on every load: a cached ``index.html`` keeps
    pointing at the previous build's hashed bundle, so a rebuilt UI
    would not show until the cache expired.
    """

    async def get_response(
        self, path: str, scope: starlette.types.Scope
    ) -> starlette.responses.Response:
        try:
            response = await super().get_response(path, scope)
        except starlette.exceptions.HTTPException as err:
            is_route = (
                err.status_code == 404
                and not path.startswith("api/")
                and "." not in path.rsplit("/", 1)[-1]
            )
            if not is_route:
                raise
            response = await super().get_response("index.html", scope)
        if response.media_type == "text/html":
            response.headers["cache-control"] = "no-cache"
        return response


def create_app(
    settings: issettin.OperantSettings,
    *,
    context_factory: Optional[context.ContextBuilder] = None,
) -> fastapi.FastAPI:
    """
    Build the operator FastAPI application from ``settings``.

    :param settings: The loaded settings the app binds to.
    :param context_factory: Overrides how run contexts are wired; tests
        inject a scripted factory so no real macOS session is driven.
    :return: The configured FastAPI application.
    """
    token = _resolve_token(settings)
    factory = context_factory or context.RunContextFactory(settings)

    @contextlib.asynccontextmanager
    async def lifespan(
        app: fastapi.FastAPI,
    ) -> collections.abc.AsyncIterator[None]:
        state = _build_state(settings, asyncio.get_running_loop(), token, factory)
        deps.install(app, state)
        try:
            yield
        finally:
            state.database.close()

    app = fastapi.FastAPI(title="Operant", version="1", lifespan=lifespan)
    common.install_error_handlers(app)

    @app.get("/healthz")
    def healthz() -> common.HealthResponse:
        health = common.HealthResponse()
        return health

    if settings.server.cors_origins:
        app.add_middleware(
            cors.CORSMiddleware,
            allow_origins=settings.server.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Mount the versioned API behind bearer auth.
    api = fastapi.APIRouter(
        prefix=_API_PREFIX,
        dependencies=[fastapi.Depends(common.bearer_dependency(token))],
    )
    for module in (arruns, hitl, catalog, secrets, system):
        api.include_router(module.router)
    app.include_router(api)

    # Serve the built frontend when a static dir is configured.
    if settings.server.static_dir is not None:
        app.mount(
            "/",
            SpaStaticFiles(directory=settings.server.static_dir, html=True),
            name="ui",
        )
    return app
