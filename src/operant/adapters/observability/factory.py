"""
Build the configured tracer.

Import as:

import operant.adapters.observability.factory as aofactor
"""

from __future__ import annotations

import importlib.util
import os

import operant.application.discovery.observe as dsobserv
import operant.domain.errors as errors
import operant.infra.settings as settings
import operant.ports.tracing as pttracin

_KEYS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")


def tracer(config: settings.ObservabilitySettings) -> pttracin.Tracer:
    """
    Return the tracer for ``config.backend``.

    :param config: The observability settings group.
    :return: A Langfuse tracer, or the no-op tracer when tracing is off.
    :raises errors.ConfigError: If Langfuse is chosen but the
        ``observability`` extra or its keys are missing.
    """
    chosen: pttracin.Tracer
    if config.backend == "langfuse":
        # Fail loudly: a silently untraced run would look like a bug.
        if importlib.util.find_spec("langfuse") is None:
            raise errors.ConfigError(
                "tracing needs the observability extra "
                "(uv sync --extra observability)"
            )
        missing = [key for key in _KEYS if not os.environ.get(key)]
        if missing:
            raise errors.ConfigError(f"Langfuse tracing needs {missing}")
        import langfuse
        import operant.adapters.observability.langfuse_tracer as aolangtr

        chosen = aolangtr.LangfuseTracer(
            langfuse.Langfuse(host=config.host), content=config.content
        )
    else:
        # Tracing is off.
        chosen = dsobserv.NoopTracer()
    return chosen
