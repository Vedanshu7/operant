"""
Entry point for ``operant serve``: run the operator app under uvicorn.

Import as:

import operant.server.runner as runner
"""

from __future__ import annotations

import uvicorn

import operant.helpers.logging as logging
import operant.infra.settings as issettin
import operant.server.app as saapp

_LOG = logging.get_logger(__name__)


def run(settings: issettin.OperantSettings) -> None:
    """
    Serve the operator web app.

    :param settings: The loaded settings the server binds to.
    """
    _LOG.info(
        "operant serving on http://%s:%s",
        settings.server.host,
        settings.server.port,
    )
    app = saapp.create_app(settings)
    uvicorn.run(
        app,
        host=settings.server.host,
        port=settings.server.port,
        log_level="info",
    )
