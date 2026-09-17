"""
The observability port: record model calls as generations in a trace.

Import as:

import operant.ports.tracing as pttracin
"""

from __future__ import annotations

import contextlib
from typing import Any, Optional, Protocol, runtime_checkable

import operant.domain.models.llm as llm

# #############################################################################
# Generation
# #############################################################################


@runtime_checkable
class Generation(Protocol):
    """
    One in-flight model call being traced.
    """

    def finish(self, turn: llm.LlmTurn, *, output: Optional[str]) -> None:
        """
        Record the call's answer, model and token usage.

        :param turn: what the model answered.
        :param output: the answer as traced text, or ``None`` to omit
            it.
        """
        ...


# #############################################################################
# Tracer
# #############################################################################


@runtime_checkable
class Tracer(Protocol):
    """
    Send model calls and eval scores to an observability backend.
    """

    def generation(
        self, trace: llm.TraceContext, *, model: str, prompt: Optional[Any]
    ) -> contextlib.AbstractContextManager[Generation]:
        """
        Open a generation around one model call.

        :param trace: where the call belongs.
        :param model: the model id being called.
        :param prompt: the already redacted prompt, or ``None`` to omit
            it.
        :return: a context manager yielding the open generation.
        """
        ...

    def score(
        self, *, trace_id: str, name: str, value: float, comment: str = ""
    ) -> None:
        """
        Attach a numeric score (1.0/0.0 for pass/fail) to a trace.

        :param trace_id: the trace to score.
        :param name: score name, e.g. ``passed``.
        :param value: the score.
        :param comment: optional explanation.
        """
        ...

    def flush(self) -> None:
        """
        Send everything buffered before the process moves on.
        """
        ...
